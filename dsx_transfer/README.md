# DSX-Transfer

Contract-first package for DSX-Transfer. The initial capability is Guarded Transfer: malware-aware, policy-enforced file movement with a scan gate before destination commit.

This is a sibling package to dsx-connect, intended to reuse shared DSX scanner, policy, audit, and job-state concepts without becoming a dsx-connect connector.

See [docs/index.md](docs/index.md) for architecture notes, scanner and policy design, audit/checkpoint semantics, integration targets, and roadmap.
