from dsx_connect_ng.config import AppSettings


def rabbitmq_topology_summary(settings: AppSettings) -> dict:
    return {
        "exchanges": {
            "jobs": settings.rabbitmq.job_exchange,
            "retry": settings.rabbitmq.retry_exchange,
            "dead_letter": settings.rabbitmq.dead_letter_exchange,
        },
        "routing_keys": {
            "scan.requested": "scan.requested",
            "scan.completed": "scan.completed",
            "scan.failed": "scan.failed",
            "policy.requested": "policy.requested",
            "policy.completed": "policy.completed",
            "policy.failed": "policy.failed",
            "dianna.requested": "dianna.requested",
            "dianna.completed": "dianna.completed",
            "dianna.failed": "dianna.failed",
            "remediation.requested": "remediation.requested",
            "remediation.completed": "remediation.completed",
            "remediation.failed": "remediation.failed",
            "result_sink.emit.requested": "result_sink.emit.requested",
            "result_sink.emit.completed": "result_sink.emit.completed",
            "result_sink.emit.failed": "result_sink.emit.failed",
        },
        "legacy_routing_keys": {
            "delivery.requested": "result_sink.emit.requested",
            "delivery.completed": "result_sink.emit.completed",
            "delivery.failed": "result_sink.emit.failed",
        },
        "queues": {
            "scan": {
                "work": "dsx.ng.scan",
                "retry": "dsx.ng.scan.retry",
                "dlq": "dsx.ng.scan.dlq",
                "priority": "highest",
            },
            "remediation": {
                "work": "dsx.ng.remediation",
                "retry": "dsx.ng.remediation.retry",
                "dlq": "dsx.ng.remediation.dlq",
                "priority": "medium",
            },
            "policy": {
                "work": "dsx.ng.policy",
                "retry": "dsx.ng.policy.retry",
                "dlq": "dsx.ng.policy.dlq",
                "priority": "high",
            },
            "dianna": {
                "work": "dsx.ng.dianna",
                "retry": "dsx.ng.dianna.retry",
                "dlq": "dsx.ng.dianna.dlq",
                "priority": "low",
            },
            "result_sink": {
                "work": "dsx.ng.result_sink",
                "retry": "dsx.ng.result_sink.retry",
                "dlq": "dsx.ng.result_sink.dlq",
                "priority": "medium",
            },
        },
        "retry_policy": {
            "scan": "strong_retry_and_dlq",
            "policy": "strong_retry_without_rescan",
            "dianna": "bounded_retry_without_rescan",
            "remediation": "bounded_retry_without_rescan",
            "result_sink": "bounded_retry_without_rescan",
        },
        "retry_runtime": {
            "max_attempts": settings.rabbitmq.retry_max_attempts,
            "delay_ms": settings.rabbitmq.retry_delay_ms,
            "header": "x-dsx-retry-attempt",
        },
        "dlq_strategy": "rabbitmq_dead_letter_exchange",
    }
