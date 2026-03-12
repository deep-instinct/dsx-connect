# Connectors (Docker Compose)

Choose a connector to deploy with Docker Compose. Each link stays in this section.

<div class="grid cards" markdown>

-   :material-folder: **Filesystem**

    ---

    Scan files from local directories or mounted storage. Best for local folders, mounted SMB/NFS, on-host workflows.

    [Deploy with Docker Compose](../filesystem.md)

-   :material-google-cloud: **Google Cloud Storage**

    ---

    Scan objects in GCS buckets. Best for GCP, bucket-based workflows.

    [Deploy with Docker Compose](../google-cloud-storage.md)

-   :material-microsoft-sharepoint: **SharePoint**

    ---

    Scan SharePoint document libraries. Best for Microsoft 365 team repos.

    [Deploy with Docker Compose](../sharepoint.md)

-   :material-microsoft-onedrive: **OneDrive**

    ---

    Scan OneDrive folders via Microsoft Graph. Best for personal/team OneDrive.

    [Deploy with Docker Compose](../onedrive.md)

-   :material-email: **M365 Mail**

    ---

    Scan Outlook / Exchange Online mailboxes. Best for email security.

    [Deploy with Docker Compose](../m365-mail.md)

-   :material-cloud: **Salesforce**

    ---

    Scan Salesforce ContentVersion and attachments. Best for CRM content.

    [Deploy with Docker Compose](../salesforce.md)

-   :material-aws: **AWS S3** *(reference architecture)*

    ---

    Scan S3 buckets. Best for AWS-native storage.

    [Deploy with Docker Compose](../aws-s3.md)

-   :material-microsoft-azure: **Azure Blob Storage** *(reference architecture)*

    ---

    Scan Azure Storage blobs. Best for Azure container/prefix workflows.

    [Deploy with Docker Compose](../azure-blob.md)

</div>

For a catalog with both Docker Compose and Kubernetes options, see [Connectors](/connectors/).
