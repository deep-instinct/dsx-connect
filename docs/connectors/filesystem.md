# Filesystem Connector (Overview)

The Filesystem connector performs a full scan over a directory and can monitor for new/modified files. It implements the standard DSX‑Connector API (`full_scan`, `read_file`, `item_action`, `webhook_event`, `repo_check`) and remains stateless — scanning and decisions happen in DSX‑Connect.

## Full Scan and Actions
- `full_scan`: enumerates files and posts scan requests to DSX‑Connect asynchronously.
- `read_file`: streams file bytes to DSX‑Connect when a worker requests content.
- `item_action`: deletes/moves/tags based on policy when a file is malicious.

## Example Diagram

![Filesystem Connector Example](../assets/filesystem-connector-example.png)

> Filters: Use the centralized rsync‑like filter rules in Reference → [Filters](../reference/filters.md).
