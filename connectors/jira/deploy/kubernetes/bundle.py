"""Build the source bundle used by the temporary lab runtime (no credentials)."""
import sys
import tarfile
from pathlib import Path

root = Path(__file__).resolve().parents[4]
output = Path(sys.argv[1] if len(sys.argv) > 1 else '/tmp/jira-runtime.tgz')
with tarfile.open(output, 'w:gz') as archive:
    for directory in ('connectors/framework', 'connectors/jira', 'shared'):
        for path in sorted((root / directory).rglob('*.py')):
            if 'tests' not in path.relative_to(root).parts and '__pycache__' not in path.parts:
                archive.add(path, arcname=str(path.relative_to(root)))
    archive.add(root / 'connectors/__init__.py', arcname='connectors/__init__.py')
print(output)
