from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from types import SimpleNamespace

import jwt

from app.config.settings import settings
from app.storage.minio_client import MinIOClient, object_key_from_url


def test_signed_download_is_scoped_expires_and_closes_connection(client, monkeypatch):
    client_wrapper = MinIOClient.__new__(MinIOClient)
    client_wrapper.bucket_name = settings.MINIO_BUCKET
    key = 'files/test/sample.txt'
    url = client_wrapper.get_presigned_url(key)
    assert url.startswith('/api/storage/') and 'minio:9000' not in url
    assert object_key_from_url(url) == key
    events = []
    response = SimpleNamespace(headers={'Content-Type': 'text/html'}, stream=lambda size: iter([b'payload']),
                               close=lambda: events.append('close'), release_conn=lambda: events.append('release'))
    def get_object(bucket, name):
        assert bucket == settings.MINIO_BUCKET and name == key
        return response
    monkeypatch.setattr('app.api.storage.MinIOClient', lambda: SimpleNamespace(client=SimpleNamespace(get_object=get_object)))
    result = client.get(url)
    assert result.status_code == 200 and result.content == b'payload'
    assert result.headers['content-type'] == 'application/octet-stream'
    assert events == ['close', 'release']
    assert client.get(url.replace('sample.txt', 'other.txt')).status_code == 403
    assert client.get(urlparse(url).path + '?token=invalid').status_code == 403
    expired = jwt.encode({'aud': 'storage', 'bucket': settings.MINIO_BUCKET, 'object': key,
                          'exp': datetime.now(timezone.utc) - timedelta(seconds=1)},
                         settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    assert client.get(urlparse(url).path + '?token=' + expired).status_code == 403


def test_storage_reference_extraction_supports_previous_urls():
    assert object_key_from_url(f'https://storage.example/{settings.MINIO_BUCKET}/folder/a%20b.png?signature=x') == 'folder/a b.png'
    assert object_key_from_url('https://storage.example/other-bucket/private.txt') is None
