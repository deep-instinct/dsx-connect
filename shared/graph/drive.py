from __future__ import annotations

from typing import Awaitable, Callable, Dict, List, Optional, Sequence, Set, Tuple

from shared.graph.base import MSGraphClientBase
from shared.dsx_logging import dsx_logging


def build_drive_item_path(parent_reference: dict, name: str) -> str:
    """Normalize a drive item's relative path inside its drive."""
    path = (parent_reference or {}).get("path") or ""
    if path.startswith("/drive/root:"):
        path = path[len("/drive/root:"):]
    return (path.strip("/") + "/" + name).strip("/") if path else name


async def delta_changes(
    client: MSGraphClientBase,
    drive_resource: str,
    cursor: Optional[str],
    *,
    page_size: int = 200,
    select: Optional[str] = None,
    skip_deleted: bool = True,
) -> Tuple[List[dict], Optional[str]]:
    """
    Fetch drive changes since the provided delta cursor.

    Returns (items, new_cursor).
    """
    http_client = await client.get_client()
    headers = await client.auth_headers(
        extra={
            "Prefer": f"odata.maxpagesize={page_size}",
            "Accept": "application/json;odata.metadata=none",
        }
    )
    select_clause = select or "id,name,file,folder,parentReference,lastModifiedDateTime,eTag,webUrl"
    url = cursor or client.graph_url(f"{drive_resource.rstrip('/')}/root/delta?$select={select_clause}")

    collected: List[dict] = []
    new_cursor: Optional[str] = None

    while url:
        resp = await http_client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        for item in data.get("value", []):
            if skip_deleted and item.get("deleted"):
                continue
            name = item.get("name") or ""
            item_path = build_drive_item_path(item.get("parentReference") or {}, name)
            if item_path:
                item = {**item, "path": item_path}
            collected.append(item)

        next_url = data.get("@odata.nextLink")
        if next_url:
            url = next_url
            continue
        new_cursor = data.get("@odata.deltaLink")
        break

    return collected, new_cursor


async def process_drive_delta_items(
    items: Sequence[dict],
    *,
    exclude_ids: Optional[Set[str]] = None,
    path_in_scope: Callable[[Optional[str]], Tuple[bool, str]],
    enqueue_file: Callable[[str, str, dict], Awaitable[None]],
    log_prefix: str,
    base_path: str,
    filter_text: str,
    sample_limit: int = 5,
    metainfo_fn: Optional[Callable[[str, dict, str], str]] = None,
) -> Tuple[int, Dict[str, int]]:
    """
    Apply scoped filtering and enqueue callbacks for delta items common to SharePoint/OneDrive connectors.

    Returns a tuple of (enqueued_count, skip_counts).
    """
    exclude: Set[str] = set(exclude_ids or ())
    skip_counts: Dict[str, int] = {"out_of_scope": 0, "folder": 0, "no_file": 0}
    enqueued = 0
    sampler_limit = max(0, sample_limit)
    metainfo = metainfo_fn or (lambda normalized, item, item_id: normalized or item.get("name") or item_id)

    for item in items:
        item_id = str(item.get("id") or "").strip()
        if not item_id or item_id in exclude:
            continue
        path = item.get("path") or item.get("name") or ""
        in_scope, normalized = path_in_scope(path)
        if not in_scope:
            skip_counts["out_of_scope"] += 1
            if skip_counts["out_of_scope"] <= sampler_limit:
                dsx_logging.debug(
                    f"{log_prefix} delta skip (out-of-scope) item_id={item_id} path='{path}' "
                    f"base='{base_path}' filter='{filter_text}'"
                )
            continue
        if item.get("folder") and not item.get("file"):
            skip_counts["folder"] += 1
            if skip_counts["folder"] <= sampler_limit:
                dsx_logging.debug(f"{log_prefix} delta skip (folder) item_id={item_id} path='{path}'")
            continue
        if not item.get("file"):
            skip_counts["no_file"] += 1
            if skip_counts["no_file"] <= sampler_limit:
                dsx_logging.debug(f"{log_prefix} delta skip (no file) item_id={item_id} path='{path}'")
            continue
        try:
            await enqueue_file(item_id, metainfo(normalized, item, item_id), item)
            enqueued += 1
        except Exception as exc:
            dsx_logging.warning(f"{log_prefix} delta enqueue failed for item {item_id}: {exc}")

    if any(skip_counts.values()):
        dsx_logging.debug(
            f"{log_prefix} delta skip summary: out_of_scope={skip_counts['out_of_scope']} "
            f"folder={skip_counts['folder']} no_file={skip_counts['no_file']} "
            f"(logged first {sampler_limit} per type)"
        )

    return enqueued, skip_counts
