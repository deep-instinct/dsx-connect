# Roadmap

## Current

- filesystem source adapter
- filesystem sink adapter
- static verdict scan gate
- DSXA stream scan gate seam
- Guarded Transfer policy evaluator
- detected file type policy rules
- transfer engine
- JSONL audit
- JSON checkpoint
- Typer CLI

## Next

1. Add report output separate from append-only audit.
2. Add bounded item-level concurrency.
3. Add live DSXA integration test mode.
4. Add GCS sink adapter for filesystem -> GCS.
5. Add by-path scanner mode for large-file/special deployments.

## Then

1. Filesystem -> S3.
2. Filesystem -> Azure Blob.
3. SDK extraction around the engine.
4. MOVEit integration.
5. GoAnywhere or Fortra integration.
6. AWS DataSync-style cloud migration integrations.
