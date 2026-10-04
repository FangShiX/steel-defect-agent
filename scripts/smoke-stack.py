"""Exercise a disposable CI stack with real DB and object storage through Nginx."""
import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--base-url', default='http://127.0.0.1:8080')
parser.add_argument('--env-file', type=Path, default=Path('.env.production'))
args = parser.parse_args()
config = dict(line.split('=', 1) for line in args.env_file.read_text().splitlines() if line and not line.startswith('#'))


def call(path, method='GET', data=None, token=None, content_type='application/json'):
    headers = {'Content-Type': content_type}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    body = json.dumps(data).encode() if isinstance(data, dict) else data
    with urlopen(Request(args.base_url + path, data=body, headers=headers, method=method), timeout=30) as response:
        return json.load(response)


health = call('/api/health/detail')['data']
assert health['status'] == 'healthy', health
token = call('/api/auth/login', 'POST', {'username': 'admin', 'password': config['BOOTSTRAP_ADMIN_PASSWORD']})['access_token']
assert call('/api/scenes')
boundary = uuid4().hex
body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="release-smoke.txt"\r\n'
        'Content-Type: text/plain\r\n\r\nrelease smoke\r\n' + f'--{boundary}--\r\n').encode()
item = call('/api/files', 'POST', body, token, 'multipart/form-data; boundary=' + boundary)
path = '/api/files/' + str(item['id'])
assert item['status'] == 'active'
with urlopen(args.base_url + item['download_url'], timeout=30) as download:
    assert download.read() == b'release smoke'
assert call(path + '/archive', 'POST', token=token)['status'] == 'archived'
assert call(path + '/restore', 'POST', token=token)['status'] == 'active'
assert call(path, 'DELETE', token=token)['status'] == 'deleted'
assert call('/api/files', token=token) == []
print('Real-stack smoke passed: Nginx, authentication, PostgreSQL/pgvector, Redis, MinIO and file lifecycle')
