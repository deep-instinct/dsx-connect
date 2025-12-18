# Rsync‑Like Filter Rules

The `DSXCONNECTOR_FILTER` follows rsync include/exclude semantics. Leave empty ("") to scan everything under `DSXCONNECTOR_ASSET`.

- `?` matches any single character except a slash (/)
- `*` matches zero or more non‑slash characters
- `**` matches zero or more characters, including slashes
- `-` / `--exclude` exclude the following match
- `+` / `--include` include the following match
- Tokens can be comma‑separated or space‑separated; quote tokens that contain spaces

Examples (paths are relative to `DSXCONNECTOR_ASSET`):

| DSXCONNECTOR_FILTER                                   | Description                                                                 |
|-------------------------------------------------------|-----------------------------------------------------------------------------|
| ""                                                    | All files recursively (no filter)                                           |
| "*"                                                   | Only top‑level files (no recursion)                                         |
| "prefix/**"                                           | Everything under `prefix/` (common for “prefix” scoping)                    |
| "sub1"                                                | Files within subtree `sub1` (recurse into subtrees)                         |
| "sub1/*"                                              | Files directly under `sub1` (no recursion)                                  |
| "sub1/sub2"                                           | Files within subtree `sub1/sub2` (recurse)                                   |
| "*.zip,*.docx"                                        | All files with .zip and .docx extensions                                    |
| "-tmp --exclude cache"                                | Exclude `tmp` and `cache` directories                                       |
| "sub1 -tmp --exclude sub2"                            | Include `sub1` subtree but exclude `tmp` and `sub2`                         |
| "test/2025*/*"                                        | Files in subtrees matching `test/2025*/*` (no recursion)                    |
| "test/2025*/** -sub2"                                 | Recurse under `test/2025*/**`, excluding any `sub2` subtree                 |
| "'scan here' -'not here' --exclude 'not here either'" | Quoted tokens for names with spaces                                          |
