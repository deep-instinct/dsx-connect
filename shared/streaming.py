import io


def stream_blob(blob: io.BytesIO, chunk_size: int = 1024 * 1024):
    while True:
        chunk = blob.read(chunk_size)
        if not chunk:
            break
        yield chunk