"""Package tracked source only; omit secrets and runtime assets."""
import argparse
import hashlib
from pathlib import Path, PurePosixPath
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def excluded(name):
    path = PurePosixPath(name)
    return (any(part in {'.git', '.venv', 'node_modules', 'dist', 'logs', 'runs', 'datasets', 'uploads', 'models', 'docx', '__pycache__'} for part in path.parts)
            or (path.name.startswith('.env') and not path.name.endswith('.example'))
            or path.suffix.lower() in {'.pt', '.pth', '.onnx', '.engine', '.log', '.sqlite', '.db', '.pem', '.key', '.pyc'})


def package(output):
    files = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode('utf-8').split('\0')
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            if name and not excluded(name) and (ROOT / name).is_file():
                archive.write(ROOT / name, 'steel-defect-agent/' + name)
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + '.sha256').write_text(f'{checksum}  {output.name}\n', encoding='utf-8')
    print(f'Packaged {output.name} with SHA-256 checksum')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/steel-defect-agent-v0.1.0.zip')
    package(parser.parse_args().output.resolve())
