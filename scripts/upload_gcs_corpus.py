from __future__ import annotations

import argparse
from pathlib import Path

from connectors.google_cloud_storage.gcs_client import GCSClient


def upload_tree(source_dir: Path, bucket: str, dest_prefix: str) -> tuple[int, int]:
    client = GCSClient()
    files = sorted(path for path in source_dir.rglob("*") if path.is_file())
    uploaded = 0
    failed = 0
    base_prefix = dest_prefix.strip("/")

    for path in files:
        rel = path.relative_to(source_dir).as_posix()
        target = f"{base_prefix}/{rel}" if base_prefix else rel
        try:
            client.upload_file(path, target, bucket)
            uploaded += 1
            print(f"uploaded {uploaded}/{len(files)} {target}", flush=True)
        except Exception as exc:
            failed += 1
            print(f"failed {target}: {exc}", flush=True)

    return uploaded, failed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--dest-prefix", required=True)
    args = parser.parse_args()

    source_dir = Path(args.source_dir).expanduser().resolve()
    uploaded, failed = upload_tree(source_dir, args.bucket, args.dest_prefix)
    print(f"done uploaded={uploaded} failed={failed}", flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
