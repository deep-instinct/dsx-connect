## Required Settings

`DSXCONNECTOR_ASSET`

Defines the host directory to scan.

Example:

```bash
DSXCONNECTOR_ASSET=/mnt/DESKTOP1/share
```

This host directory will be mounted into the container at:

```text
/app/scan_folder
```

---

`DSXCONNECTOR_ITEM_ACTION`

Defines what happens to malicious files.

Common values:

* `nothing` (report only)
* `move` (quarantine)
* `delete`

If using `move`, also set:

`DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO`

Defines the directory to move quarantined files to.
```bash
DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO=/var/lib/dsxconnect/quarantine-DESKTOP1
```
