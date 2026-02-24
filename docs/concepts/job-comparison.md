# Job Comparison Explained

The Job Comparison view provides structured performance metrics for completed scan jobs.

It allows you to compare multiple jobs side-by-side and understand:

* Overall throughput
* DSXA scan performance
* End-to-end processing cost
* Latency characteristics
* Capacity projections

This page explains what each metric represents and how to interpret it.

For step-by-step tuning guidance, see [Operations → Performance Tuning](../operations/performance-tuning-job-comparisons.md).

---

## What a Job Represents

A Job is a logical scan operation initiated via:

* UI
* API
* Scheduled or automated trigger

A Job consists of many individual **Scan Requests**, each representing one file.

Job metrics aggregate performance across all files processed in that scan.

---

## Core Throughput Metrics

### Job Time

Total elapsed time from job start to completion.

This is the primary end-to-end performance indicator.

It includes:

* Enumeration
* File retrieval
* DSXA scanning
* Verdict handling
* Result persistence

---

### Total Bytes

The total size of all files processed in the job.

This represents workload volume.

---

### Total Bytes/sec

End-to-end throughput across the entire system.

Formula (conceptually):

```id="v7fl6h"
Total Bytes ÷ Job Time
```

This includes:

* Connector I/O
* Network transfer
* DSXA scan time
* Queue overhead
* Remediation time

This metric reflects overall system performance.

---

### Scan Bytes/sec

Throughput inside DSXA only.

This excludes:

* Enumeration time
* File retrieval latency
* Connector overhead

If Scan Bytes/sec is stable but Total Bytes/sec drops, the bottleneck is likely outside DSXA.

---

## Latency Metrics

### Avg Req ms

Average time required to process a single file request.

This includes:

* Connector read time
* Network transfer
* DSXA processing
* Verdict handling

Higher values may indicate:

* Large files
* Slow connectors
* Network latency
* DSXA saturation

---

### Scan ms/byte

Average scanning cost per byte inside DSXA.

This allows comparison across different file size distributions.

Useful for estimating how scan performance scales with larger datasets.

---

## Progress Metrics

### Processed

Number of items processed versus total items discovered.

Indicates job completion progress.

---

### Status

Indicates whether the job completed successfully, failed, or was interrupted.

---

## Projection Metrics

The Job Comparison view provides normalized estimates such as:

* Estimated Job Time: 1GB
* Estimated Job Time: 1TB
* Estimated Job Time: 1M files
* Estimated DSXA Time: 1GB
* Estimated DSXA Time: 1TB

These projections are derived from:

* Observed throughput
* Observed file size distribution
* Observed scan cost per byte

They allow you to answer questions like:

* “How long would 5TB take?”
* “What happens if this dataset doubles?”
* “Is this throughput acceptable for my SLA?”

---

## Understanding DSXA Time vs Job Time

Two different projections are provided:

* **Estimated DSXA Time** — time spent inside scanning only.
* **Estimated Job Time** — full end-to-end processing time.

If DSXA Time is much lower than Job Time:

* Enumeration or connector I/O likely dominates.

If DSXA Time closely matches Job Time:

* Scanning itself is the primary bottleneck.

---

## Interpreting Differences Between Jobs

When comparing jobs:

Look for changes in:

* Total Bytes/sec
* Scan Bytes/sec
* Avg Req ms
* Estimated projections

Differences may indicate:

* Infrastructure saturation
* Different file mixes
* Changes in concurrency or replicas
* Changes in connector configuration
* Changes in DSXA capacity

The Job Comparison view does not prescribe tuning steps.
It provides measurement data for informed decisions.

## Important Notes on Projections

Projections are estimates based on the scanned dataset.

Accuracy depends on:

* File size distribution
* File type mix
* Network conditions
* DSXA characteristics

Always validate projections using representative datasets.


## Measurement Before Modification

The purpose of Job Comparison is measurement.

It allows you to:

* Establish a baseline
* Compare configuration changes
* Quantify performance gains
* Evaluate cost/performance tradeoffs



