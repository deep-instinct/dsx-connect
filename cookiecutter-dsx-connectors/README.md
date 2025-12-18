# Using Cookie Cutter to Generate DSX-Connector Skeleton Code

1. Install cookie cutter (if needed) 
2. Navigate to the directory where cookiecutter.json resides
3. You can edit the cookiecutter.json to change defaults, but typically what you should do is run cookie cutter and override on the prompts.
4. Run cookie cutter 
```
cookiecutter -o some_output_folder -f .
```
You will then be asked a series of prompts the third prompt is "repository".  Repository should be general name for the 
repository your connector connects to.  So in this example, in the prompt I override the Filesystem default value with
"GCP Buckets".

```shell
[1/14] full_name (Logan Gilbert): 
[2/14] email (logang@deepinstinct.com): 
[3/14] repository (Filesystem): GCP Buckets         
[4/14] project_name (GCP Buckets Connector): 
[5/14] project_slug (gcp_buckets_connector): 
```
What you will note as that this changes the defaults for many of the remaining prompts.  
Note that project_name now defaults to "GCP Buckets Connector" and project_slug to "gcp_buckets_connector".

## Prompt Definitions
- **repository** - Gives a name for the repository the connector connects to, e.g. Filesystem, SFTP, GCP Buckets, AWS S3, OCI Buckets, etc....).  Use Camel Case.
- **project_name** - A formatted name for this connector typically used in documentation
- **project_slug** - Converted project name to use lowercase and underscores.  Used for python module names.
- **__release_name** - (hidden, not prompted) The project_slug converted to use hyphens for release names (e.g. filesystem-connector-<version>)
- **project_short_description** - Used in documentation
- **version** - the version number for start with.  Used with __release_name when creating packaged code and docker images.
- **connector_port** - the default port used by this connector
- **docker_repo** - remote docker hub repo to use when creating releases.  

## Post‑generation tips
- Prefer friendly names: Set `DSXCONNECTOR_DISPLAY_NAME` (optional) to show a human‑friendly card title in the dsx-connect UI without changing the connector slug or routes.
- Custom icon: Set `DSXCONNECTOR_DISPLAY_ICON` to a data URI (recommended), raw `<svg ...>` markup, or an emoji (e.g., `🗂️`). The UI will safely render data URIs or encode raw SVG. If unset, a built‑in icon is used based on the connector slug.
- Shared framework: Templates rely on `connectors.framework.dsx_connector` and shared models under `shared/`; ensure your repo layout mirrors dsx-connect.
- TLS: Base config already includes TLS flags; see connector deploy README for `DSXCONNECTOR_USE_TLS`, `DSXCONNECTOR_VERIFY_TLS`, and `DSXCONNECTOR_CA_BUNDLE` usage.

# Using
Once the template code is generated move the directory and files created under "some_output_folder" to the 
"connectors" module in this project.
