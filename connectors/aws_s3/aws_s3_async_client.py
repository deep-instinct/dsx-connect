import hashlib
import io
import logging
import pathlib

import aioboto3
import tenacity
from botocore.config import Config
from botocore.exceptions import ClientError

import os

from shared import file_ops
from shared.dsx_logging import dsx_logging
import asyncio

# Initialize the S3 client outside the handler to reuse it across invocations
# s3_client = boto3.client('s3')
CHUNK_SIZE = int(os.getenv('CHUNK_SIZE', 1024 * 1024))


class AWSS3AsyncClient:
    """
    Manages file AWS-related bucket services.

    Extensions to this service can be used to 'extend' the file scanning capabilities of
    DPA, for example scans that fallback to file reputation services in the event a file is too
    large, or unsupported.
    """

    def __init__(self, concurrent_processing_max: int = 10, s3_endpoint_url: str = None,
                 s3_endpoint_verify: bool = True):
        self._chunk_size = CHUNK_SIZE
        self.concurrent_processing_max = concurrent_processing_max
        dsx_logging.debug(f'Allowing ({concurrent_processing_max}) concurrent S3 object processing')

        self.s3_session = aioboto3.Session()
        if s3_endpoint_url and not s3_endpoint_url.strip():  # check if s3_endpoint_url is a blank string and set to None so it's not used in client and resource
            s3_endpoint_url = None
        else:
            dsx_logging.debug(f"Using s3_endpoint_url {s3_endpoint_url} for connection to AWS bucket")

        self.s3_endpoint_url = s3_endpoint_url
        self.s3_endpoint_verify = s3_endpoint_verify
        self.config = Config(max_pool_connections=concurrent_processing_max)

    async def create_s3_client(self):
        # Use aioboto3's client method to create the client
        session = self.s3_session
        if not self.s3_endpoint_url:
            client = session.client('s3', verify=self.s3_endpoint_verify, config=self.config)
        else:
            client = session.client('s3', endpoint_url=self.s3_endpoint_url, verify=self.s3_endpoint_verify,
                                    config=self.config)
        return client

    async def buckets(self):
        s3_client = await self.create_s3_client()
        async with s3_client as client:
            response = await client.list_buckets()
            return [bucket['Name'] for bucket in response.get('Buckets', [])]

    async def delete_object(self, source_bucket: str, key: str):
        s3_client = await self.create_s3_client()
        async with s3_client as client:
            await client.delete_object(Bucket=source_bucket, Key=key)

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(3),
        wait=tenacity.wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
        before_sleep=tenacity.before_sleep_log(dsx_logging, log_level=logging.WARN)  # Log before waiting to retry
    )
    async def get_object(self, bucket_name: str, key: str) -> io.BytesIO:
        try:
            s3_client = await self.create_s3_client()
            async with s3_client as client:
                response = await client.get_object(Bucket=bucket_name, Key=key)
                dsx_logging.debug(f'Retrieved S3 bucket object: {key}')

                content = io.BytesIO()
                async for chunk in response['Body']:
                    content.write(chunk)
                content.seek(0)

                if len(content.getvalue()) == 0:
                    raise ValueError(f"Retrieved object {key} is empty.")
                return content

        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                dsx_logging.error(f'Object {key} not found in bucket {bucket_name}.')
            else:
                dsx_logging.error(f"ClientError in get_object for {bucket_name}/{key}: {e}")
            raise e
        except ValueError as ve:
            dsx_logging.error(f'Validation error for object {key}: {ve}')
            raise
        except Exception as e:
            dsx_logging.error(f'Unexpected error retrieving object {key}: {e}')
            raise

    async def key_size(self, bucket_name: str, key: str) -> int:
        s3_client = await self.create_s3_client()
        async with s3_client as client:
            response = await client.head_object(Bucket=bucket_name, Key=key)
            return response['ContentLength']

    async def keys(self, bucket_name: str, prefix: str = '', delimiter: str = '/', start_after: str = '',
                   recursive: bool = False, include_folders: bool = False):
        """
        Retrieves a list of keys (objects) in a specified bucket with optional filtering.
        """
        dsx_logging.info(f"Listing keys for bucket: {bucket_name}, prefix: {prefix}, recursive: {recursive}")

        s3_client = await self.create_s3_client()
        async with s3_client as client:
            paginator = client.get_paginator('list_objects_v2')
            async for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix,
                                                 Delimiter=delimiter if not recursive else '', StartAfter=start_after):
                for obj in page.get('Contents', []):
                    if not include_folders and obj['Key'].endswith('/'):
                        continue
                    yield obj

                if include_folders and 'CommonPrefixes' in page:
                    for prefix_obj in page['CommonPrefixes']:
                        yield prefix_obj['Prefix']

    async def upload_bytes_async(self, content: io.BytesIO, file_key: str, dest_bucket_name: str):
        s3_client = await self.create_s3_client()
        async with s3_client as client:
            await client.put_object(Bucket=dest_bucket_name, Key=file_key, Body=content)

    async def upload_file_async(self, filepath: pathlib.Path, file_key: str, dest_bucket_name: str):
        try:
            content = await file_ops.read_file_async(filepath, chunk_size=CHUNK_SIZE)
            await self.upload_bytes_async(content, file_key, dest_bucket_name)
        except Exception as e:
            dsx_logging.error(f'Error uploading to {dest_bucket_name}. Cause: {e}')
            raise

    async def upload_folder_async(self, folder: pathlib.Path, dest_bucket_name: str, recursive: bool = True):
        file_paths = file_ops.get_filepaths(folder, recursive=recursive)
        tasks = []
        for full_path in file_paths:
            if full_path.is_file():
                tasks.append(self.upload_file_async(full_path, full_path.name, dest_bucket_name))

        await asyncio.gather(*tasks)

    async def calculate_sha256(self, bucket_name: str, key: str) -> str:
        dsx_logging.debug(f'Getting {key} in {bucket_name}.')

        try:
            content = await self.get_object(bucket_name, key)
            sh = hashlib.sha256()
            for chunk in iter(lambda: content.read(self._chunk_size), b''):
                sh.update(chunk)
            sha256_hash = sh.hexdigest()
            dsx_logging.debug(f'sha256 hash for {key}: {sha256_hash}')
            return sha256_hash
        except Exception as e:
            msg = f'Error retrieving {key} from {bucket_name} and calculating hash'
            dsx_logging.error(f"{msg}: {e}")
            raise FileNotFoundError(msg)

    async def test_s3_connection(self, bucket_name) -> bool:
        """
        Test the connection to an AWS S3 bucket. Throws an exception if connection fails.
        """
        try:
            buckets = await self.buckets()
            return bucket_name in buckets
        except Exception as e:
            dsx_logging.error(f"Error testing connection: {e}")
            raise
