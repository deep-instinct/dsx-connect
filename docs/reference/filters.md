# Rsync‑Like Filter Rules

The `DSXCONNECTOR_FILTER` follows rsync include/exclude semantics for scoping scans under a connector’s asset root.

- `?` matches any single character except a slash (/)
- `*` matches zero or more non‑slash characters
- `**` matches zero or more characters, including slashes
- `-` / `--exclude` exclude the following match
- `+` / `--include` include the following match (everything else is implicitly included unless a later exclude removes it)
- Tokens can be comma‑separated or space‑separated; quote tokens with spaces
- Prefix `+`/`-` directly onto the pattern (no space) or use the long forms `--include pattern`, `--exclude pattern`.
- When mixing includes/excludes, add explicit `+` rules to keep intent clear (e.g., include only `/Finance/**` before dropping `tmp/`).

Examples (paths are relative to `DSXCONNECTOR_ASSET`):

| Filter                                             | Description                                                                                                               |
|----------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------|
| ""                                                 | All files recursively (no filter)                                                                                         |
| "*"                                                | Only top‑level files (no recursion)                                                                                       |
| "prefix/**"                                        | Everything under `prefix/` (common for “prefix” scoping)                                                                  |
| "sub1"                                             | Files within subtree `sub1` (recurse into subtrees)                                                                       |
| "sub1/*"                                           | Files directly under `sub1` (no recursion)                                                                                |
| "sub1/sub2"                                        | Files within subtree `sub1/sub2` (recurse)                                                                                |
| "*.zip,*.docx"                                     | All files with .zip and .docx extensions                                                                                  |
| "-tmp --exclude cache"                             | Exclude `tmp` and `cache` directories                                                                                     |
| "sub1 -tmp --exclude sub2"                         | Include `sub1` subtree but exclude `tmp` and `sub2`. Same as `+sub1/** -tmp --exclude sub2` or `--include sub1 -tmp -sub2` |
| "'scan here' -'not here' --exclude 'not here either'" | Quoted tokens for names with spaces                                                                                       |
| "+Finance/**, -**"                                 | Include only `Finance/` subtree and drop everything else.                                                                 |
| "+**/*.pdf, -tmp/**"                               | Keep PDFs anywhere but drop anything under a `tmp/` folder.                                                               |
| "--include Finance/** --include Legal/** -**"      | Two explicit include rules followed by a drop-everything-else exclude.                                                    |
