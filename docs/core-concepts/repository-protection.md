# Repository Monitoring and Scanning

Repository protection covers both the inventory of repository content and the evaluation of that content. Monitoring and scanning are related, but they answer different operational questions.

## Monitor repositories

Monitoring discovers repositories, records their assets, and observes changes. It provides the control plane with an up-to-date view of what exists and what needs evaluation. Change events can reduce the amount of content that must be rescanned, while scheduled discovery can detect changes that are not delivered through events.

## Scan repositories

Scanning evaluates content against the configured protection policy. A scan may be a baseline of an existing repository, an incremental scan triggered by a change, or an explicitly requested scan of a selected scope.

The scan flow should preserve enough context to answer:

- which asset and repository produced the file;
- which application or job requested the evaluation;
- which scanner and policy version evaluated it;
- what finding or disposition was produced.

## Disposition

A scan result is not only a detection record. It can drive an operational disposition such as allow, block, quarantine, or remediation. The control plane should retain the relationship between the finding and the action so operators can explain and repeat the decision.

For the v2 operational view, see [Quarantine and Remediation](../dsx-connect-2/operations/quarantine-and-remediation.md).

