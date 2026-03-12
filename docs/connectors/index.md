# Connector Catalog

<div class="grid cards" markdown>

-   :material-folder: **Filesystem**

    ---

    Scan files from local directories or mounted storage.

    **Best for**

    - Local folders
    - Mounted SMB / NFS shares
    - On-host scanning workflows

    [Docker Compose](../deployment/docker/filesystem.md) ·
    [Kubernetes](../deployment/kubernetes/filesystem.md)

-   :material-google-cloud: **Google Cloud Storage**

    ---

    Scan objects stored in GCS buckets.

    **Best for**

    - Cloud-native storage
    - GCP environments
    - Bucket-based workflows

    [Docker Compose](../deployment/docker/google-cloud-storage.md) ·
    [Kubernetes](../deployment/kubernetes/google-cloud-storage.md)

-   :material-microsoft-sharepoint: **SharePoint**

    ---

    Scan documents stored in SharePoint libraries.

    **Best for**

    - Team document repositories
    - Microsoft 365 environments

    [Docker Compose](../deployment/docker/sharepoint.md) ·
    [Kubernetes](../deployment/kubernetes/sharepoint.md)

-   :material-microsoft-onedrive: **OneDrive**

    ---

    Scan files in OneDrive folders via Microsoft Graph.

    **Best for**

    - Personal/team OneDrive
    - Microsoft 365 environments

    [Docker Compose](../deployment/docker/onedrive.md) ·
    [Kubernetes](../deployment/kubernetes/onedrive.md)

-   :material-email: **M365 Mail**

    ---

    Scan Outlook / Exchange Online mailboxes (messages and attachments).

    **Best for**

    - Email security
    - Microsoft 365 mail

    [Docker Compose](../deployment/docker/m365-mail.md) ·
    [Kubernetes](../deployment/kubernetes/m365-mail.md)

-   :material-cloud: **Salesforce**

    ---

    Scan files in Salesforce (ContentVersion, attachments).

    **Best for**

    - Salesforce CRM content
    - Connected App / JWT auth

    [Docker Compose](../deployment/docker/salesforce.md) ·
    [Kubernetes](../deployment/kubernetes/salesforce.md)

-   :material-aws: **AWS S3** *(reference architecture)*

    ---

    Scan objects in S3 buckets (list/read, optional move/delete).

    **Best for**

    - AWS-native storage
    - Bucket-based workflows

    [Docker Compose](../deployment/docker/aws-s3.md) ·
    [Kubernetes](../deployment/kubernetes/aws-s3.md)

-   :material-microsoft-azure: **Azure Blob Storage** *(reference architecture)*

    ---

    Scan blobs in Azure Storage containers.

    **Best for**

    - Azure-native storage
    - Container/prefix workflows

    [Docker Compose](../deployment/docker/azure-blob.md) ·
    [Kubernetes](../deployment/kubernetes/azure-blob.md)

</div>
