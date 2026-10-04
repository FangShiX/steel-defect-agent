from app.core.redis_client import RedisClient
from app.entity.db_models import ChatMessage, ChatSession, User
from app.storage.cleanup import cleanup_stale_agent_uploads
import main


def test_redis_cleanup_lock_only_releases_its_own_token(monkeypatch):
    calls = []

    class FakeRedis:
        def set(self, *args, **kwargs):
            calls.append(("set", args, kwargs))
            return True

        def eval(self, *args):
            calls.append(("eval", args, {}))
            return 1

    monkeypatch.setattr("app.core.redis_client.redis.from_url", lambda *_args, **_kwargs: FakeRedis())
    client = RedisClient()

    assert client.acquire_lock("cleanup", "token-1", 60) is True
    client.release_lock("cleanup", "token-1")
    assert calls[0] == ("set", ("cleanup", "token-1"), {"nx": True, "ex": 60})
    assert calls[1][0] == "eval"
    assert calls[1][1][1:] == (1, "cleanup", "token-1")


def test_cleanup_runner_skips_when_another_worker_owns_lock(monkeypatch):
    class Lock:
        def acquire_lock(self, *_args):
            return False

        def release_lock(self, *_args):
            raise AssertionError("a lock that was not acquired must not be released")

    monkeypatch.setattr(main, "redis_client", Lock())
    monkeypatch.setattr(main, "SessionLocal", lambda: (_ for _ in ()).throw(AssertionError("database must not be opened")))

    assert main.retry_resource_cleanups() == {"attempted": 0, "succeeded": 0, "skipped": True}


def test_cleanup_runner_releases_lock_after_retry(monkeypatch):
    events = []

    class Lock:
        def acquire_lock(self, *_args):
            events.append("acquire")
            return True

        def release_lock(self, *_args):
            events.append("release")

    class Database:
        def close(self):
            events.append("close")

    monkeypatch.setattr(main, "redis_client", Lock())
    monkeypatch.setattr(main, "SessionLocal", Database)
    monkeypatch.setattr(main, "retry_pending_cleanups", lambda _db: {"attempted": 1, "succeeded": 1})

    assert main.retry_resource_cleanups() == {"attempted": 1, "succeeded": 1}
    assert events == ["acquire", "close", "release"]


def test_stale_agent_upload_cleanup_preserves_referenced_attachment(db_session, tmp_path):
    user = User(username="upload-cleanup", email="upload-cleanup@example.com", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    session = ChatSession(session_uuid="upload-cleanup-session", user_id=user.id, title="uploads")
    db_session.add(session)
    db_session.flush()

    referenced = tmp_path / "referenced.txt"
    stale = tmp_path / "stale.txt"
    referenced.write_text("keep", encoding="utf-8")
    stale.write_text("remove", encoding="utf-8")
    old_time = referenced.stat().st_mtime - 48 * 60 * 60
    import os
    os.utime(referenced, (old_time, old_time))
    os.utime(stale, (old_time, old_time))
    db_session.add(ChatMessage(
        session_id=session.id,
        role="user",
        content="attachment",
        attachments=[{"path": str(referenced)}],
    ))
    db_session.commit()

    assert cleanup_stale_agent_uploads(db_session, tmp_path, max_age_seconds=24 * 60 * 60) == 1
    assert referenced.exists()
    assert not stale.exists()
