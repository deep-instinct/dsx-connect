from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
from urllib.parse import quote

from connectors.sharepoint.config import ConfigManager
from connectors.sharepoint.sharepoint_client import SharePointClient


def resolve_sharepoint_asset(cfg) -> None:
    asset = (cfg.asset or "").strip()
    if asset.startswith("http://") or asset.startswith("https://"):
        host, site, drive_name, _rel_path = SharePointClient.parse_sharepoint_web_url(asset)
        if not cfg.sp_hostname:
            cfg.sp_hostname = host
        if not cfg.sp_site_path:
            cfg.sp_site_path = site
        if drive_name and not cfg.sp_drive_name:
            cfg.sp_drive_name = drive_name


async def upload_tree(source_dir: Path, dest_folder: str, concurrency: int) -> tuple[int, int]:
    cfg = ConfigManager.reload_config()
    resolve_sharepoint_asset(cfg)
    client = SharePointClient(cfg)
    await client.ensure_folder(dest_folder)

    files = sorted(p for p in source_dir.rglob("*") if p.is_file())
    sem = asyncio.Semaphore(max(1, concurrency))
    uploaded = 0
    failed = 0

    async def upload_one(path: Path) -> None:
        nonlocal uploaded, failed
        rel = path.relative_to(source_dir).as_posix()
        target = f"{dest_folder.strip('/')}/{rel}"
        encoded_target = "/".join(quote(part, safe="") for part in target.split("/"))
        try:
            async with sem:
                parent = os.path.dirname(target)
                if parent:
                    await client.ensure_folder(parent)
                content = path.read_bytes()
                await client.upload_file(encoded_target, content)
                uploaded += 1
                print(f"uploaded {uploaded}/{len(files)} {target}", flush=True)
        except Exception as exc:
            failed += 1
            print(f"failed {target}: {exc}", flush=True)

    await asyncio.gather(*(upload_one(path) for path in files))
    return uploaded, failed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--dest-folder", required=True)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()

    source_dir = Path(args.source_dir).expanduser().resolve()
    if not source_dir.is_dir():
        raise SystemExit(f"source dir not found: {source_dir}")

    uploaded, failed = asyncio.run(upload_tree(source_dir, args.dest_folder, args.concurrency))
    print(f"done uploaded={uploaded} failed={failed}", flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
