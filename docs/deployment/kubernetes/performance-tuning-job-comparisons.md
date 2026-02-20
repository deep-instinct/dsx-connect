# Performance Tuning with Job Comparisons

This guide shows how to use the DSX-Connect Console's Job Comparison feature to tune performance. The goal is to run repeatable scans, compare results, and adjust concurrency/replicas to improve throughput without overloading the cluster.

## Workflow

1. Deploy DSX-Connect with defaults (or your chosen `replicaCount` and `celery.concurrency`).
2. Register a connector pointing to a representative data set (ideally 100–1000+ files).
3. Run a full scan.
4. Open **Job Comparison** in the Console and compare the completed jobs.
5. Adjust worker parallelism (see guidance below).
6. Re-run the scan and compare again.

## Job Comparison Fields

| Field | Description | Why it matters |
|---|---|---|
| Job | Job ID | Use to compare runs of the same dataset |
| Status | Completion state | Confirms the job finished before comparing |
| Processed | Processed vs total items | Ensures you scanned the same dataset |
| Job time | Overall job runtime | Primary performance indicator |
| Total Bytes | Total bytes scanned | Indicates data volume |
| Total bytes/sec | End-to-end throughput | Shows impact of tuning |
| Scan bytes/sec | DSXA scan throughput | Isolates DSXA performance |
| Avg Req ms | Average per-file request time | Captures connector + DSXA latency |
| Scan ms/byte | Per-byte scan cost | Helps compare across file sizes |
| Est DSXA Scan Time: 1GB | Projected DSXA scan time for 1 GB | Normalized DSXA cost |
| Est Job Time: 1GB | Projected end-to-end time for 1 GB | Normalized total cost |
| Est DSXA Scan Time: 1TB | Projected DSXA scan time for 1 TB | Normalized DSXA cost |
| Est Job Time: 1TB | Projected end-to-end time for 1 TB | Normalized total cost |
| Est DSXA Scan Time: 1M files | Projected DSXA scan time for 1M files | Normalized DSXA cost |
| Est Job Time: 1M files | Projected end-to-end time for 1M files | Normalized total cost |

Tip: Run the same dataset and avoid changing connector filters between tests so comparisons are meaningful.

## Job Comparison UI

![Job Comparison UI](../../assets/job_comparison_ui.png)

## Scaling DSX-Connect: Concurrency and Replicas

Workers scale with two knobs. Use them together for best results:

Terminology:
- Replica count (`replicaCount`): number of pods. Each pod has its own CPU/memory limits/requests and its own Celery process. Good for horizontal scaling and resilience.
- Concurrency (`celery.concurrency`): number of task workers inside one pod. Increases parallelism within a pod; shares that pod’s resources.
- Task: tasks are processed by the workers. 
  - One such task is a scan request, which is processed by a Scan Request worker.
  - Scan Request Workers queue Verdict tasks, which are processed by a Verdict worker.
  - Verdict Workers queue results tasks, which are processed by a Results worker. 
- Task queue: a queue of tasks waiting to be processed.
- Job: a set of all tasks initiated by a user (via the UI or API). A job can contain multiple scan requests.

- `concurrency` adds to speed of processing tasks (and a job) by adding Worker parallelism.  
- `replicaCount` adds Worker fault tolerance and parallelism by adding more pods of a particular worker type. 
- Increasing replicas does add parallelism, but it is usually less efficient than increasing concurrency first.

### Practical Tuning Tips

- The scan request workers are generally the place to start with concurrency. These workers take enqueued scan requests, read a file from a connector, and send it to DSXA for scanning. It is by far the most time‑consuming and resource‑intensive worker.
- Default scan_request concurrency is `2`, so each scan_request pod can handle two scan requests at a time. Adding another pod doubles that (e.g., 2 pods × 2 concurrency = 4 total workers).
- Start by raising `celery.concurrency` modestly (2–4), then add `replicaCount` to spread load across nodes.
- If when increasing concurrency you notice CPU/memory saturation within a pod, increase pod resources or add replicas.
- Scale downstream workers (verdict/result/notification) when increasing request throughput to avoid bottlenecks.

Example configuration:

| Concurrency | Replicas | Scan Request Workers |
|---|---|---|
| 2 | 2 | 4 |

This gives good parallelism and resiliency, for a total of 4 scan request workers.

## Re-run and Compare

After each tuning change, re-run the same full scan and compare jobs side-by-side. Look for:
- Lower total duration
- Higher throughput
- Stable error/skip rates
- Similar verdict breakdowns

Stop tuning when throughput gains flatten or resource usage becomes too high for your cluster.
