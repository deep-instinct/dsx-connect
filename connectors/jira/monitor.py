"""Polling with durable checkpoints and idempotent job submission."""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path


class Checkpoints:
    def __init__(self, path):
        path = Path(path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS seen (scope TEXT, attachment TEXT, PRIMARY KEY(scope, attachment))')
        self.db.execute('CREATE TABLE IF NOT EXISTS baselines (scope TEXT PRIMARY KEY)')
        self.db.commit()

    def initialized(self, scope):
        return self.db.execute('SELECT 1 FROM baselines WHERE scope=?', (scope,)).fetchone() is not None

    def seen(self, scope, attachment):
        return self.db.execute('SELECT 1 FROM seen WHERE scope=? AND attachment=?', (scope, attachment)).fetchone() is not None

    def baseline(self, scope, attachments):
        with self.db:
            self.db.executemany('INSERT OR IGNORE INTO seen VALUES (?, ?)', [(scope, a) for a in attachments])
            self.db.execute('INSERT OR IGNORE INTO baselines VALUES (?)', (scope,))

    def mark(self, scope, attachment):
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO seen VALUES (?, ?)', (scope, attachment))

    def close(self):
        self.db.close()


class JiraMonitor:
    def __init__(self, client, state, include, submit):
        self.client, self.state, self.include, self.submit = client, state, include, submit

    async def poll_scope(self, integration_id, scope):
        jql = scope['resource_selector']
        configured = self.client.config.asset
        if configured and configured != jql:
            jql = f'({configured}) AND ({jql})'
        # Complete discovery before changing the first-run baseline. A failed page
        # cannot silently mark a partial traversal initialized.
        attachments = [(key, a) async for key, a in self.client.attachments(jql) if self.include(a)]
        namespace = f'{self.client.cloud_id}:{integration_id}'
        if not self.state.initialized(namespace):
            self.state.baseline(namespace, [str(a['id']) for _, a in attachments])
            return {'baseline': len(attachments), 'submitted': 0}
        submitted = 0
        for issue_key, attachment in attachments:
            aid = str(attachment['id'])
            if self.state.seen(namespace, aid):
                continue
            filename = attachment['filename']
            payload = {
                'job_type': 'scan.batch', 'integration_id': integration_id, 'scope_id': scope['scope_id'],
                'idempotency_key': 'jira-monitor:' + hashlib.sha256(f'{namespace}:{aid}'.encode()).hexdigest(),
                'payload': {'source': 'connector_monitor', 'scanOnly': True},
                'items': [{
                    'object_identity': f'jira://{self.client.cloud_id}/attachment/{aid}',
                    'payload': {'readerStrategy': 'proxy', 'path': aid, 'metainfo': filename,
                                'sizeInBytes': attachment.get('size'), 'scanOnly': True,
                                'attribution': {'file_name': filename, 'jira_issue_key': issue_key}},
                }],
            }
            # Mark only after successful API acceptance. Retrying after an ambiguous
            # timeout reuses the same idempotency key.
            await self.submit(payload)
            self.state.mark(namespace, aid)
            submitted += 1
        return {'baseline': 0, 'submitted': submitted}
