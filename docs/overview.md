# DSX‑Connect Overview

DSX‑Connect is a modular integration framework that orchestrates safe, scalable file scanning and remediation while remaining completely agnostic to specific repository integrations. The core “scan brain” handles queuing, parallelism, and remediation; DSX‑Connectors adapt repositories (Filesystem, S3, GCS, SharePoint/OneDrive, GitHub, etc.) to a simple, consistent API.

## Key Components

- **DSX‑Connect (Core):**
  - Receives scan requests, fetches file content from connectors, invokes scanning, and applies remediation.
  - Scales from one file to billions using queues and horizontally scalable workers.
  - Integration‑agnostic: depends only on a stable connector API.

- **DSX‑Connectors (Connectors):**
  - Connectors implement a consistent API and focus on the specifics of a repository.
  - Easily extendable: add new connectors to support new repositories.
  - Stateless and can be deployed independently.

## Architecture Advantages

- **Clear delineation:** DSX-Connect core orchestrates scanning, verdict handling, logging, etc...; connectors handle repository specific semantics (list/read/actions).
- **Event‑driven:** Queues decouple enumeration, scanning, and remediation for high throughput and resilience.
- **Fault tolerant & HA:** Retries with exponential backoff, dead letter queues (DLQ), graceful degradation.
- **Scalable:** Core Worker pools handle parallelism and scaling; connectors operate independently.
- **Flexible:** Add new repositories by writing a connector; core components stay the same.
- **Consistent & pluggable:** All connectors share the same API contract; updating one doesn’t disrupt others.
- **Observability:** Health endpoints, queue metrics, DLQ management, structured logs.

## Example Workflow

The following diagram illustrates a simplified workflow of DSX-Connect, deployed with Scan Request and Verdict workers, and a Filesystem Connector.  First,
a quick overview of connector APIs relevavnt to this example:

- `full_scan`: enumerate items and enqueue scan requests (streaming enumeration recommended)
- `read_file`: retrieve file content (binary stream)
- `item_action`: perform remediation (delete/move/tag)

Filesystem Connector deployed with access to a folder: ~/Documents, and quarantine folder set to ~/Documents/quarantine.

1. DSX-Connect triggers a `full_scan` on the connector then...
2. the connector lists all files in ~/Documents and for each file...
3. sends Scan Requests to DSX-Connect which queues each request.  
4. DSX‑Connect Scan Request Worker dequeues a Scan Request and... 
5. Requests the file from the connector (`read_file`), and...
6. scan the file with DSXA and places the DSXA verdict in the Verdict Queue.
7. Verdict Worker dequeues a verdict and then, on a malicious verdict,
8. calls on the connector's `item_action` to take action the connector (delete/move/tag the file). In this case, the Filesystem Connector moves the file to ~/Documents/quarantine.

Benefits of decoupling: resiliency (queue persistence), scale (parallel workers), and isolation (enumeration doesn’t block scanning).

### Filesystem Example (Image)

![Filesystem Connector Example](assets/filesystem-connector-example.png)

## Architecture Overview

![DSX‑Connect Architecture](assets/drawio/dsx-connect-design.svg)

Mermaid diagram:  

```mermaid
flowchart LR
%% Define Repositories (left column)
    subgraph Repositories["File Repositories"]
        AWSRepo["AWS S3"]
        AzureRepo["Azure Blob Storage"]
        GCPRepo["Google Cloud Storage"]
        FSRepo["Filesystem"]
    end

%% Define Connectors (middle column)
    subgraph Connectors["DSX-Connectors"]
        AWSConn["AWS Connector"]
        AzureConn["Azure Connector"]
        GCPConn["GCP Connector"]
        FSConn["Filesystem Connector"]
    end

%% Define Core System (right column)
    subgraph DSX["DSX-Connect Core"]
      direction TB
      API["API (FastAPI)"]
      SRQ["Scan Request Queue"]
      SRW["Scan Request Worker"]
      VQ["Verdict Queue"]
      VW["Verdict Worker"]
      RQ["Scan Result Queue"]
      RW["Scan Result Worker"]
      RSYS["rsyslog / stdout"]
      STATS["Stats"]
      RDB["Results DB"]

      %% Force a vertical flow
      API --> SRQ
      SRQ --> SRW
      SRW --> VQ
      VQ --> VW
      VW --> RQ
      RQ --> RW
      RW --> RSYS
      RW --> STATS
      RW --> RDB
    end

%% Relationships (bidirectional)
    AWSRepo <--> AWSConn
    AzureRepo <--> AzureConn
    GCPRepo <--> GCPConn
    FSRepo <--> FSConn

    AWSConn <--> API
    AzureConn <--> API
    GCPConn <--> API
    FSConn <--> API

%% Styling for clarity
    classDef repo fill:#e3f2fd,stroke:#1565c0,color:#0d47a1,stroke-width:1px;
    classDef conn fill:#e3f2fd,stroke:#1565c0,color:#0d47a1,stroke-width:1px;
    classDef core fill:#fff3e0,stroke:#ef6,color:#9c6a00,stroke-width:1px;
    classDef queue fill:#ffe0b2,stroke:#ef6,color:#9c6a00,stroke-width:1px;
    classDef worker fill:#e8f5e9,stroke:#2e7d32,color:#1b5e20,stroke-width:1px;
    class AWSConn,AzureConn,GCPConn,FSConn conn;
    class SRQ,VQ,RQ queue;
    class SRW,VW,RW worker;

```

Below is a high‑level Mermaid diagram that complements the static overview:


## Sequence: Full Scan (Mermaid)

This is a more detailed sequence adapted from the Confluence page.

```mermaid
sequenceDiagram
    participant UI as Web UI/API Client
    participant DSX as DSX-Connect Core
    participant Queue as Redis Queue
    participant Worker as Celery Worker
    participant Conn as Connector
    participant Repo as Repository
    participant DSXA as DSXA Scanner

    Note over UI, DSXA: Full Scan Initiation Flow

    UI->>+DSX: POST /connectors/full_scan/{uuid}
    DSX->>+Conn: POST /{connector}/full_scan
    Note over DSX, Conn: Background task initiated

    Conn->>+Repo: List/enumerate items
    Repo-->>-Conn: Item keys/paths

    loop For each item
        Conn->>Conn: Build ScanRequest(location, metainfo)
        Conn->>+DSX: POST /scan/request
        DSX->>+Queue: Enqueue scan_request_task
        Queue-->>-DSX: Task queued
        DSX-->>-Conn: {status: success, message: queued}
    end

    Conn-->>-DSX: Full scan invoked (enqueued)
    DSX-->>-UI: Full scan initiated

    Note over UI, DSXA: Asynchronous Processing of Queued Scans

    loop For each queued scan request
        Worker->>+Queue: Pop scan_request_task
        Queue-->>-Worker: ScanRequest data
        Worker->>+Conn: POST /{connector}/read_file
        Conn->>+Repo: Download/stream content
        Repo-->>-Conn: Blob stream
        Conn-->>-Worker: StreamingResponse (content)
        Worker->>+DSXA: POST /scan/binary/v2
        DSXA-->>-Worker: Verdict (benign/malicious)
        alt Malicious
            Worker->>+Conn: PUT /{connector}/item_action
            Conn->>+Repo: Apply action (move/tag/delete)
            Repo-->>-Conn: Action applied
            Conn-->>-Worker: ItemActionStatusResponse
        end
        Worker->>Worker: Store result / notify
    end
```

## Deployment Models

- **Docker Compose:** Ideal for evaluations and minimal production deployments.
- **Kubernetes + Helm:** Scalable, resilient, and portable across AKS/EKS/GKE/OKE. Integrates with HA Redis, object storage, and logging.  Ideal for 
   production environments connected to multiple repositories of the same or different types, high availability a necessity.

Both models use the same container images and configuration patterns, easing promotion from test to prod.

## Fault Tolerance & High Availability

- **Retries & DLQ:** Intelligent retries per failure type (connector/DSXA/timeouts/rate limits). DLQ preserves failed tasks for reprocessing.
- **Graceful degradation:** Continue accepting/queuing when downstreams are degraded; resume automatically.
- **HA patterns:** Stateless workers; shared queues; multiple API replicas; connectors operate independently.
