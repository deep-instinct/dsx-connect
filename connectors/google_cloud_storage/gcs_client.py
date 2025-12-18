from google.api_core.exceptions import NotFound, GoogleAPIError
import io, hashlib, pathlib, os
from shared import file_ops
from shared.file_ops import relpath_matches_filter, compute_prefix_hints
from shared.dsx_logging import dsx_logging

CHUNK_SIZE = int(os.getenv('CHUNK_SIZE', 1024 * 1024))


class GCSClient:
    def __init__(self):
        # Lazy init the SDK client to avoid requiring ADC during import/tests
        self._client = None
        dsx_logging.debug("Initialized GCS client wrapper (lazy SDK init)")

    def _get_client(self):
        if self._client is None:
            try:
                from google.cloud import storage  # local import to avoid hard dependency at import time
                self._client = storage.Client()
            except Exception as e:
                dsx_logging.error(f"Failed to initialize GCS storage client: {e}")
                raise
        return self._client

    def buckets(self):
        client = self._get_client()
        return [bucket.name for bucket in client.list_buckets()]

    def key_exists(self, bucket: str, key: str) -> bool:
        try:
            client = self._get_client()
            blob = client.bucket(bucket).blob(key)
            return blob.exists()
        except GoogleAPIError as e:
            dsx_logging.error(f"GCS key_exists error: {e}")
            raise

    def keys(self, bucket: str, base_prefix: str = "", filter_str: str = ""):
        """
        Yield blobs in a GCS bucket applying DSXCONNECTOR_FILTER.
        Uses prefix hints when safe and always verifies with relpath_matches_filter.
        """
        client = self._get_client()
        hints = compute_prefix_hints(filter_str or "")
        seen: set[str] = set()

        # Normalize base_prefix to either '' or 'path/'
        bp = (base_prefix or "").strip("/")
        if bp:
            bp = bp + "/"

        def _rel(key: str) -> str:
            if not bp:
                return key
            return key[len(bp):] if key.startswith(bp) else key

        def _emit(blob):
            key = blob.name
            if not key or key in seen or key.endswith('/'):
                return
            rel = _rel(key)
            if filter_str and not relpath_matches_filter(rel, filter_str):
                return
            seen.add(key)
            yield {'Key': key, 'Size': getattr(blob, 'size', None)}

        if hints:
            for prefix in sorted(set(hints)):
                eff = f"{bp}{prefix}" if bp else prefix
                for blob in client.list_blobs(bucket, prefix=eff):
                    for item in _emit(blob):
                        yield item
        else:
            if bp:
                it = client.list_blobs(bucket, prefix=bp)
            else:
                it = client.list_blobs(bucket)
            for blob in it:
                for item in _emit(blob):
                    yield item

    def get_object(self, bucket: str, key: str) -> io.BytesIO:
        try:
            client = self._get_client()
            blob = client.bucket(bucket).blob(key)
            content = io.BytesIO()
            blob.download_to_file(content)
            content.seek(0)
            return content
        except NotFound:
            raise FileNotFoundError(f"{key} not found in bucket {bucket}")
        except Exception as e:
            dsx_logging.error(f"GCS get_object error: {e}")
            raise

    def delete_object(self, bucket: str, key: str) -> bool:
        try:
            client = self._get_client()
            blob = client.bucket(bucket).blob(key)
            blob.delete()
            return True
        except NotFound:
            return False
        except Exception as e:
            dsx_logging.error(f"GCS delete_object error: {e}")
            raise

    def move_object(self, src_bucket: str, src_key: str, dest_bucket: str, dest_key: str) -> bool:
        try:
            client = self._get_client()
            source_bucket = client.bucket(src_bucket)
            source_blob = source_bucket.blob(src_key)
            destination_bucket = client.bucket(dest_bucket)

            # Copy using the destination bucket's method
            destination_bucket.copy_blob(source_blob, destination_bucket, dest_key)

            # Delete the source blob
            source_blob.delete()

            return True
        except Exception as e:
            dsx_logging.error(f"GCS move_object error: {e}")
            return False

    def tag_object(self, bucket: str, key: str, tags: dict = None) -> bool:
        try:
            client = self._get_client()
            blob = client.bucket(bucket).blob(key)
            blob.metadata = tags or {'scanned': 'true'}
            blob.patch()
            return True
        except Exception as e:
            dsx_logging.error(f"GCS tag_object error: {e}")
            return False

    def upload_bytes(self, content: io.BytesIO, key: str, bucket: str):
        client = self._get_client()
        blob = client.bucket(bucket).blob(key)
        content.seek(0)
        blob.upload_from_file(content)

    def upload_file(self, filepath: pathlib.Path, key: str, bucket: str):
        try:
            client = self._get_client()
            blob = client.bucket(bucket).blob(key)
            blob.upload_from_filename(str(filepath))
        except Exception as e:
            dsx_logging.error(f"GCS upload_file error: {e}")
            raise

    def upload_folder(self, folder: pathlib.Path, bucket: str):
        for path in file_ops.get_filepaths(folder):
            if path.is_file():
                self.upload_file(path, path.name, bucket)

    def calculate_sha256(self, bucket: str, key: str) -> str:
        try:
            content = self.get_object(bucket, key)
            sh = hashlib.sha256()
            for chunk in iter(lambda: content.read(CHUNK_SIZE), b''):
                sh.update(chunk)
            return sh.hexdigest()
        except Exception as e:
            raise FileNotFoundError(f"SHA256 calc error: {e}")

    def test_gcs_connection(self, bucket: str) -> bool:
        try:
            client = self._get_client()
            bucket_obj = client.bucket(bucket)
            _ = list(client.list_blobs(bucket_obj, max_results=1))
            return True  # If no exception, access works (even if no blobs exist)
        except Exception as e:
            dsx_logging.error(f"Failed to connect to GCS bucket {bucket}: {e}")
        return False


# for testing only
if __name__ == "__main__":
    gcs_client = GCSClient()

    keys = gcs_client.keys(bucket="lg-test-01", recursive=True, prefix="sub1/sub2")
    for key in keys:
        print(f"Key {key['Key']}")
