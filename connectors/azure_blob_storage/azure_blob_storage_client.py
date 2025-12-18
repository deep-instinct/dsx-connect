import asyncio
import io
import logging
import pathlib
import hashlib
import os
from functools import partial

from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceNotFoundError

from shared import file_ops
from shared.file_ops import relpath_matches_filter, compute_prefix_hints
from shared.dsx_logging import dsx_logging
import tenacity
import base64
import binascii
from azure.core.credentials import AzureNamedKeyCredential

CHUNK_SIZE = int(os.getenv('CHUNK_SIZE', 1024 * 1024))




def _clean(s: str) -> str:
    # Undo common IDE artifacts
    return s.strip().strip('"').strip("'").replace("\\;", ";")

def _maybe_b64_decode(s: str) -> str:
    try:
        raw = base64.b64decode(s, validate=True).decode("utf-8")
        # sanity check that it looks like a connection string
        if "AccountName=" in raw and ";" in raw:
            return raw
    except (binascii.Error, UnicodeDecodeError):
        pass
    return s

def load_blob_service_client() -> BlobServiceClient:
    # 1) plain env
    conn = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
    if conn:
        try:
            return BlobServiceClient.from_connection_string(_clean(conn))
        except Exception:
            pass  # fall through to b64/file/pair

    # 2) base64 env (preferred key name)
    decoded = _maybe_b64_decode(conn)
    if conn:
        try:
            return BlobServiceClient.from_connection_string(_clean(decoded))
        except Exception:
            pass

    # 3) name/key pair (no semicolons at all)
    name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
    key  = os.getenv("AZURE_STORAGE_ACCOUNT_KEY")
    if name and key:
        cred = AzureNamedKeyCredential(name, key)
        return BlobServiceClient(account_url=f"https://{name}.blob.core.windows.net", credential=cred)


    raise RuntimeError("No Azure Storage credentials found")



class AzureBlobClient:
    def __init__(self, connection_string: str = None):
        self._chunk_size = CHUNK_SIZE
        # if not connection_string:
        #     connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        # if not connection_string:
        #     dsx_logging.error("AzureBlobClient must be initialized with an AZURE_STORAGE_CONNECTION_STRING")
        #     raise ValueError("Missing Azure Storage connection string.")

        self.service_client = load_blob_service_client()
        # self.service_client = BlobServiceClient.from_connection_string(connection_string)
        dsx_logging.info("Initialized AzureBlobClient with given connection string")

    def containers(self) -> list:
        return [container.name for container in self.service_client.list_containers()]

    def key_exists(self, container: str, blob_name: str) -> bool:
        try:
            blob_client = self.service_client.get_blob_client(container=container, blob=blob_name)
            return blob_client.exists()
        except Exception as e:
            dsx_logging.error(f"Error checking if blob exists: {e}")
            raise

    def delete_blob(self, container: str, blob_name: str) -> bool:
        try:
            blob_client = self.service_client.get_blob_client(container=container, blob=blob_name)
            blob_client.delete_blob()
            return True
        except ResourceNotFoundError:
            return False
        except Exception as e:
            dsx_logging.error(f"Error deleting blob: {e}")
            raise

    @tenacity.retry(stop=tenacity.stop_after_attempt(3),
                    wait=tenacity.wait_exponential(multiplier=1, min=1, max=10),
                    reraise=True,
                    before_sleep=tenacity.before_sleep_log(dsx_logging, logging.WARN))
    def get_blob(self, container: str, blob_name: str) -> io.BytesIO:
        blob_client = self.service_client.get_blob_client(
            container=container, blob=blob_name
        )
        # ask the SDK to download in 8 parallel ranges
        downloader = blob_client.download_blob(max_concurrency=8)
        content = io.BytesIO()
        # stream the chunks into your BytesIO
        for chunk in downloader.chunks():
            content.write(chunk)
        content.seek(0)
        return content

    async def get_blob_async(self, container: str, blob_name: str) -> io.BytesIO:
        loop = asyncio.get_running_loop()
        # partial(self._get_blob_sync, ...) fixes the first two args
        return await loop.run_in_executor(
            None,
            partial(self.get_blob, container, blob_name)
        )



    def keys(self, container: str, base_prefix: str = "", filter_str: str = "", page_size: int | None = None):
        """
        Yield blob keys from a container applying DSXCONNECTOR_FILTER rules.

        Uses provider-side prefix narrowing when safe by deriving conservative
        prefixes from the filter (no excludes and only bare path includes), and
        always applies relpath_matches_filter client-side for correctness.
        """
        try:
            container_client = self.service_client.get_container_client(container)

            # Normalize base prefix (virtual folder) to '' or 'path/'
            bp = (base_prefix or "").strip("/")
            if bp:
                bp = bp + "/"

            # Compute conservative name_starts_with hints when possible
            hints: list[str] = compute_prefix_hints(filter_str or "")

            seen: set[str] = set()

            def _rel(key: str) -> str:
                if not bp:
                    return key
                return key[len(bp):] if key.startswith(bp) else key

            def _emit(blob):
                key = blob.name
                if key in seen:
                    return
                rel = _rel(key)
                if filter_str and not relpath_matches_filter(rel, filter_str):
                    return
                seen.add(key)
                yield {'Key': key, 'Size': getattr(blob, 'size', None)}

            def _iter_list(name_starts_with: str | None = None):
                if page_size and page_size > 0:
                    # Try various SDK signatures for page sizing across azure-core/storage versions
                    if name_starts_with:
                        try:
                            pages = container_client.list_blobs(name_starts_with=name_starts_with).by_page(page_size=page_size)
                            for page in pages:
                                for blob in page:
                                    yield blob
                            return
                        except TypeError:
                            pass
                        try:
                            pages = container_client.list_blobs(name_starts_with=name_starts_with).by_page(results_per_page=page_size)
                            for page in pages:
                                for blob in page:
                                    yield blob
                            return
                        except TypeError:
                            pass
                        try:
                            # Some versions accept results_per_page on list_blobs directly
                            for blob in container_client.list_blobs(name_starts_with=name_starts_with, results_per_page=page_size):
                                yield blob
                            return
                        except TypeError:
                            pass
                    else:
                        try:
                            pages = container_client.list_blobs().by_page(page_size=page_size)
                            for page in pages:
                                for blob in page:
                                    yield blob
                            return
                        except TypeError:
                            pass
                        try:
                            pages = container_client.list_blobs().by_page(results_per_page=page_size)
                            for page in pages:
                                for blob in page:
                                    yield blob
                            return
                        except TypeError:
                            pass
                        try:
                            for blob in container_client.list_blobs(results_per_page=page_size):
                                yield blob
                            return
                        except TypeError:
                            pass
                else:
                    if name_starts_with:
                        for blob in container_client.list_blobs(name_starts_with=name_starts_with):
                            yield blob
                    else:
                        for blob in container_client.list_blobs():
                            yield blob

            if hints:
                for prefix in sorted(set(hints)):
                    eff = f"{bp}{prefix}" if bp else prefix
                    for blob in _iter_list(name_starts_with=eff):
                        for item in _emit(blob):
                            yield item
            else:
                start = bp if bp else None
                for blob in _iter_list(name_starts_with=start):
                    for item in _emit(blob):
                        yield item
        except Exception as e:
            dsx_logging.error(f"Error listing blobs: {e}")
            raise

    def move_blob(self, src_container: str, src_blob: str, dest_container: str, dest_blob: str) -> bool:
        try:
            src_client = self.service_client.get_blob_client(container=src_container, blob=src_blob)
            dest_client = self.service_client.get_blob_client(container=dest_container, blob=dest_blob)

            dest_client.start_copy_from_url(src_client.url)
            src_client.delete_blob()
            return True
        except Exception as e:
            dsx_logging.error(f"Error moving blob: {e}")
            return False

    def upload_bytes(self, content: io.BytesIO, container: str, blob_name: str):
        blob_client = self.service_client.get_blob_client(container=container, blob=blob_name)
        blob_client.upload_blob(content.getvalue(), overwrite=True)

    def upload_file(self, filepath: pathlib.Path, container: str, blob_name: str):
        try:
            content = file_ops.read_file(filepath)
            self.upload_bytes(content, container, blob_name)
        except Exception as e:
            dsx_logging.error(f"Error uploading file {filepath} to container {container}: {e}")
            raise

    def upload_folder(self, folder: pathlib.Path, container: str, recursive: bool = True):
        file_paths = file_ops.get_filepaths(folder, recursive=recursive)
        for path in file_paths:
            if path.is_file():
                self.upload_file(path, container, path.name)

    def calculate_sha256(self, container: str, blob_name: str) -> str:
        try:
            content = self.get_blob(container, blob_name)
            sh = hashlib.sha256()
            for chunk in iter(lambda: content.read(self._chunk_size), b''):
                sh.update(chunk)
            return sh.hexdigest()
        except Exception as e:
            msg = f"Error retrieving {blob_name} from {container} and calculating hash: {e}"
            dsx_logging.error(msg)
            raise FileNotFoundError(msg)

    def tag_blob(self, container: str, blob_name: str, tags: dict = None) -> bool:
        try:
            blob_client = self.service_client.get_blob_client(container=container, blob=blob_name)
            blob_client.set_blob_metadata(metadata=tags or {"scanned": "true"})
            return True
        except Exception as e:
            dsx_logging.error(f"Error tagging blob {blob_name}: {e}")
            return False

    def test_connection(self, container: str) -> bool:
        try:
            return self.service_client.get_container_client(container).exists()
        except Exception as e:
            dsx_logging.error(f"Error testing Azure Blob container connection: {e}")
            raise


# for testing only
if __name__ == "__main__":
    ab_client = AzureBlobClient()

    keys = ab_client.keys(container="lg-test-01", recursive=True, prefix="sub1")
    for key in keys:
        print(f"Key {key['Key']}")
