### `DSXCONNECTOR_ASSET`

Defines the object store asset root to scan.

Example:

```bash
DSXCONNECTOR_ASSET=name_of_bucket_or_container
```

---
### `DSXCONNECTOR_FILTER`

Defines a rsync-like filter to apply to files and folders, such as bucket prefixes or file filters.  

* [Reference → Filter Syntax](../../reference/filters.md)

---

### `DSXCONNECTOR_ITEM_ACTION`

Defines what happens to malicious files.

Common values:

* `nothing` (report only)
* `move` (quarantine)
* `move_tag` (quarantine and tag - moves the file and adds metadata tag)`
* `delete`

If using `move`, also set:

### `DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO`

Defines an object store resource and prefix to move quarantined files to.

Using our example above:
```bash
DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO=dsx-quarantine
```
would move quarantined files to `dsx-quarantine` under the same bucket or container specified in `DSXCONNECTOR_ASSET`.
