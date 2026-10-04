"""Audit all installed distributions, normalizing official CPU wheel versions."""
import importlib.metadata
from pathlib import Path
import subprocess
import sys
import tempfile

with tempfile.TemporaryDirectory() as temporary:
    requirements = Path(temporary) / 'audit-requirements.txt'
    lines = []
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata['Name']
        version = distribution.version.split('+')[0]
        lines.append(f'{name}=={version}')
    requirements.write_text('\n'.join(sorted(set(lines))) + '\n', encoding='utf-8')
    subprocess.run([sys.executable, '-m', 'pip_audit', '--no-deps', '--disable-pip', '-r', str(requirements)], check=True)
