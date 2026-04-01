from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from connectors.onedrive.config import OneDriveConnectorConfig
from connectors.onedrive.onedrive_client import OneDriveClient


def load_runtime_config() -> OneDriveConnectorConfig:
    return OneDriveConnectorConfig()


async def upload_tree(source_dir: Path, dest_folder: str, concurrency: int) -> tuple[int, int]:
    cfg = load_runtime_config()
    client = OneDriveClient(cfg)
    files = sorted(path for path in source_dir.rglob("*") if path.is_file())
    uploaded = 0
    failed = 0
    sem = asyncio.Semaphore(max(1, concurrency))
    base = dest_folder.strip("/")

    try:
        await client.ensure_folder(base)

        async def upload_one(path: Path) -> None:
            nonlocal uploaded, failed
            rel = path.relative_to(source_dir).as_posix()
            target = f"{base}/{rel}" if base else rel
            async with sem:
                try:
                    await client.upload_file(target, path.read_bytes())
                    uploaded += 1
                    print(f"uploaded {uploaded}/{len(files)} {target}", flush=True)
                except Exception as exc:
                    failed += 1
                    print(f"failed {target}: {exc}", flush=True)

        await asyncio.gather(*(upload_one(path) for path in files))
        return uploaded, failed
    finally:
        await client.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--dest-folder", required=True)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()

    source_dir = Path(args.source_dir).expanduser().resolve()
    uploaded, failed = asyncio.run(upload_tree(source_dir, args.dest_folder, args.concurrency))
    print(f"done uploaded={uploaded} failed={failed}", flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
