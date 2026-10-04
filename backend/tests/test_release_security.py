import io

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy.engine import make_url

from app.api.scenes import upload_model_version
from app.api.files import upload_file
from app.config.settings import Settings
from app.core.security import verify_password
from app.database import seed
from app.entity.db_models import User
from app.services.file_service import file_service


def test_initial_admin_requires_explicit_secret_and_does_not_print_it(db_session, monkeypatch, capsys):
    monkeypatch.setattr(seed.settings, 'BOOTSTRAP_ADMIN_PASSWORD', '')
    with pytest.raises(ValueError, match='BOOTSTRAP_ADMIN_PASSWORD'):
        seed.seed_admin_user(db_session, {})
    assert db_session.query(User).count() == 0
    password = 'test-only-unique-admin-password'
    monkeypatch.setattr(seed.settings, 'BOOTSTRAP_ADMIN_PASSWORD', password)
    admin = seed.seed_admin_user(db_session, {})
    assert verify_password(password, admin.hashed_password)
    assert password not in capsys.readouterr().out
    monkeypatch.setattr(seed.settings, 'BOOTSTRAP_ADMIN_PASSWORD', '')
    assert seed.seed_admin_user(db_session, {}).id == admin.id


@pytest.mark.asyncio
async def test_untrusted_user_cannot_upload_executable_checkpoint(db_session):
    user = User(username='untrusted', email='untrusted@example.com', hashed_password='x')
    db_session.add(user)
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        await upload_model_version(scene_id=1, file=UploadFile(filename='untrusted.pt', file=io.BytesIO(b'x')),
                                   version='1', model_name='x', current_user=user, db=db_session)
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_file_upload_rejects_oversize_before_storage(db_session, monkeypatch):
    monkeypatch.setattr(file_service, 'MAX_FILE_SIZE', 8)
    user = User(id=1)
    with pytest.raises(HTTPException) as error:
        await upload_file(file=UploadFile(filename='x.txt', file=io.BytesIO(b'123456789')),
                          current_user=user, db=db_session)
    assert error.value.status_code == 413


def test_database_credentials_with_special_characters_round_trip():
    config = Settings(_env_file=None, DEBUG=True, DB_USER='user@example', DB_PASSWORD='pass:@%/word')
    parsed = make_url(config.DATABASE_URL)
    assert parsed.username == config.DB_USER
    assert parsed.password == config.DB_PASSWORD
