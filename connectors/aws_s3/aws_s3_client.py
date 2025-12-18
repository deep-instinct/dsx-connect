import hashlib
import io
import logging
import pathlib
import os

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from shared import file_ops
from shared.file_ops import relpath_matches_filter, compute_prefix_hints
from shared.dsx_logging import dsx_logging
import tenacity

CHUNK_SIZE = int(os.getenv('CHUNK_SIZE', 1024 * 1024))


class AWSS3Client:
    def __init__(self, concurrent_processing_max: int = 10, s3_endpoint_url: str = None,
                 s3_endpoint_verify: bool = True):
        self._chunk_size = CHUNK_SIZE
        self.s3_endpoint_url = s3_endpoint_url if s3_endpoint_url and s3_endpoint_url.strip() else None
        self.s3_endpoint_verify = s3_endpoint_verify
        self.config = Config(max_pool_connections=concurrent_processing_max)

        self.s3_client = boto3.client(
            's3',
            endpoint_url=self.s3_endpoint_url,
            verify=self.s3_endpoint_verify,
            config=self.config
        )
        dsx_logging.info(f"Initialized S3 client with endpoint {self.s3_endpoint_url}")

    def buckets(self):
        response = self.s3_client.list_buckets()
        return [bucket['Name'] for bucket in response.get('Buckets', [])]

    def delete_object(self, bucket: str, key: str):
        """
        Deletes an object from the specified S3 bucket.

        Args:
            bucket (str): The name of the S3 bucket.
            key (str): The key of the object to delete.

        Returns:
            bool: True if the object was deleted successfully, False if the object did not exist.
        """
        try:
            self.s3_client.delete_object(Bucket=bucket, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            dsx_logging.error(f"Error deleting object {key} from bucket {bucket}: {e}")
            raise

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(3),
        wait=tenacity.wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
        before_sleep=tenacity.before_sleep_log(dsx_logging, log_level=logging.WARN)
    )
    def get_object(self, bucket: str, key: str) -> io.BytesIO:
        try:
            response = self.s3_client.get_object(Bucket=bucket, Key=key)
            content = io.BytesIO(response['Body'].read())
            if len(content.getvalue()) == 0:
                raise ValueError(f"Retrieved object {key} is empty.")
            content.seek(0)
            return content
        except ClientError as e:
            dsx_logging.error(f"ClientError getting object {key} from {bucket}: {e}")
            raise
        except Exception as e:
            dsx_logging.error(f"Unexpected error: {e}")
            raise

    def key_exists(self, bucket: str, key: str) -> bool:
        """
        Check whether a key exists in the specified S3 bucket.

        Args:
            bucket (str): The name of the S3 bucket.
            key (str): The object key to check.

        Returns:
            bool: True if the key exists, False otherwise.
        """
        try:
            self.s3_client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            dsx_logging.error(f"Error checking key existence for {key} in bucket {bucket}: {e}")
            raise

    def key_size(self, bucket: str, key: str) -> int:
        response = self.s3_client.head_object(Bucket=bucket, Key=key)
        return response['ContentLength']

    def keys(self, bucket: str, base_prefix: str = "", filter_str: str = ""):
        """
        Yield S3 object keys applying DSXCONNECTOR_FILTER.

        Uses safe prefix narrowing when possible and always verifies with
        relpath_matches_filter client-side to ensure correctness.
        """
        paginator = self.s3_client.get_paginator('list_objects_v2')
        hints = compute_prefix_hints(filter_str or "")

        seen: set[str] = set()

        # Normalize base_prefix to either '' or 'path/'
        bp = (base_prefix or "").strip("/")
        if bp:
            bp = bp + "/"

        def _rel(key: str) -> str:
            if not bp:
                return key
            if key.startswith(bp):
                return key[len(bp):]
            # Shouldn't happen when Prefix=bp is used, but guard anyway
            return key

        def _emit(obj):
            key = obj.get('Key') or obj.get('Prefix')
            if not key or key in seen:
                return
            if key.endswith('/'):
                return
            # Apply filter relative to base_prefix root
            rel = _rel(key)
            if filter_str and not relpath_matches_filter(rel, filter_str):
                return
            seen.add(key)
            yield obj if 'Size' in obj else {'Key': key}

        if hints:
            for prefix in sorted(set(hints)):
                eff = f"{bp}{prefix}" if bp else prefix
                for page in paginator.paginate(Bucket=bucket, Prefix=eff):
                    for obj in page.get('Contents', []):
                        for item in _emit(obj):
                            yield item
        else:
            # Narrow to base_prefix if provided; otherwise whole bucket
            paginate_kwargs = {'Bucket': bucket}
            if bp:
                paginate_kwargs['Prefix'] = bp
            for page in paginator.paginate(**paginate_kwargs):
                for obj in page.get('Contents', []):
                    for item in _emit(obj):
                        yield item

    def move_object(self, src_bucket: str, src_key: str, dest_bucket: str, dest_key: str) -> bool:
        """
        Moves an object from one bucket/key to another by copying then deleting the original.

        Args:
            src_bucket (str): Source bucket name.
            src_key (str): Source object key.
            dest_bucket (str): Destination bucket name.
            dest_key (str): Destination object key.

        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            copy_source = {'Bucket': src_bucket, 'Key': src_key}
            self.s3_client.copy_object(CopySource=copy_source, Bucket=dest_bucket, Key=dest_key)
            self.delete_object(src_bucket, src_key)
            return True
        except ClientError as e:
            dsx_logging.error(f"Failed to move {src_key} from {src_bucket} to {dest_bucket}/{dest_key}: {e}")
            return False

    def tag_object(self, bucket: str, key: str, tags: dict = None) -> bool:
        """
        Applies tags to an S3 object.

        Args:
            bucket (str): The bucket name.
            key (str): The object key.
            tags (dict): A dictionary of tags to apply. Defaults to {'scanned': 'true'}.

        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            tag_set = [{'Key': k, 'Value': v} for k, v in (tags or {'scanned': 'true'}).items()]
            self.s3_client.put_object_tagging(
                Bucket=bucket,
                Key=key,
                Tagging={'TagSet': tag_set}
            )
            return True
        except ClientError as e:
            dsx_logging.error(f"Failed to tag object {key} in bucket {bucket}: {e}")
            return False

    def upload_bytes(self, content: io.BytesIO, file_key: str, bucket: str):
        self.s3_client.put_object(Bucket=bucket, Key=file_key, Body=content.getvalue())

    def upload_file(self, filepath: pathlib.Path, file_key: str, bucket: str):
        try:
            content = file_ops.read_file(filepath)
            self.upload_bytes(content, file_key, bucket)
        except Exception as e:
            dsx_logging.error(f"Error uploading file {filepath} to {bucket}: {e}")
            raise

    def upload_folder(self, folder: pathlib.Path, bucket: str):
        file_paths = file_ops.get_filepaths(folder)
        for path in file_paths:
            if path.is_file():
                self.upload_file(path, path.name, bucket)

    def calculate_sha256(self, bucket: str, key: str) -> str:
        try:
            content = self.get_object(bucket, key)
            sh = hashlib.sha256()
            for chunk in iter(lambda: content.read(self._chunk_size), b''):
                sh.update(chunk)
            return sh.hexdigest()
        except Exception as e:
            msg = f"Error retrieving {key} from {bucket} and calculating hash: {e}"
            dsx_logging.error(msg)
            raise FileNotFoundError(msg)

    def test_s3_connection(self, bucket: str) -> bool:
        try:
            return bucket in self.buckets()
        except Exception as e:
            dsx_logging.error(f"Error testing S3 connection: {e}")
            raise
