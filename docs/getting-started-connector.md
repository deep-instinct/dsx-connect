# Deploying Your First Connector (Filesystem)

Bring up the sample filesystem connector on the shared bridge network, point it at a host folder, and run a quick scan.

## 1) Pick a test folder
```bash
mkdir -p ~/Documents/dsx-connect-test
# (optional) drop a few files into the folder to scan
```

## 2) Configure the connector via the sample env file
In the extracted bundle:
```bash
cd filesystem-connector-<version>
cp sample.filesystem.env .filesystem.env
```

Then edit `.filesystem.env` to set:
```dotenv
DSXCONNECTOR_ASSET=/Users/<you>/Documents/dsx-connect-test
DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO=/Users/<you>/Documents/dsx-connect-test/dsxconnect-quarantine
#DSXCONNECTOR_ITEM_ACTION=move   # options: nothing, delete, tag, move, move_tag
```

The env file sets the bind-mount paths so the connector can read and quarantine files from your host without editing YAML (the compose file mounts `DSXCONNECTOR_ASSET` to `/app/scan_folder` and `DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO` to `/app/quarantine` inside the container).
If you want to see the quarantine folder in action, uncomment and set `DSXCONNECTOR_ITEM_ACTION=move`.
For least surprise, keep the quarantine folder outside the scan path; the connector also auto-skips the configured quarantine path to prevent re-scans.

## 3) Start the connector
```bash
docker compose --env-file filesystem-connector-<version>/.filesystem.env \
  -f filesystem-connector-<version>/docker-compose-filesystem-connector.yaml up -d
```
Within a few seconds the connector registers with DSX-Connect and begins monitoring the folder (`DSXCONNECTOR_MONITOR=true` by default).

## 4) Explore the UI and run a scan
1. Browse to `http://localhost:8586`.
2. On the **Connectors** tab, find `filesystem connector`.
   - Gear icon: shows runtime config.
   - **Preview**: lists a handful of files to confirm the target folder.
   - **Sample Scan**: triggers scans for the first five files.
3. Try either flow:
   - **Full Scan** to enumerate every file under the test folder.
   - Drop a new file into the folder and watch it appear in **Scan Results**. If item action is set to `move`, confirm quarantined files land in the quarantine path.

![DSX-Connect UI with scan results](assets/ui_screenshot_fs.png)

*Figure: Filesystem connector scan results view.*


Done! You now have DSXA, DSX-Connect core, and a connector running together locally.

Next, explore some core Connectors concepts: 

- [Next: Connector Overview](connectors/concepts.md)
or, 
- jump to Deployment -> Docker section to learn more about Docker deployments.  
or, 
- jump to Deployment -> Kubernetes to learn about Kubernetes deployments.




## Tear down (optional)
```bash
docker compose -f docker-compose-dsx-connect-all-services.yaml down
docker compose -f docker-compose-dsxa.yaml down
docker compose -f filesystem-connector-<version>/docker-compose-filesystem-connector.yaml down
```
