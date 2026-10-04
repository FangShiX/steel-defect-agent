import pytest
from pydantic import ValidationError

import main
from app.config.settings import Settings


def test_production_settings_reject_example_secrets():
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(_env_file=None, DEBUG=False, ALLOWED_ORIGINS="https://app.example.com")


def test_production_settings_reject_localhost_cors():
    with pytest.raises(ValidationError, match="ALLOWED_ORIGINS"):
        Settings(
            _env_file=None,
            DEBUG=False,
            JWT_SECRET_KEY="x" * 32,
            DB_PASSWORD="strong-db-password",
            MINIO_SECRET_KEY="strong-minio-password",
            ALLOWED_ORIGINS="http://localhost:5173",
        )


def test_production_settings_accept_explicit_secrets_and_origin():
    settings = Settings(
        _env_file=None,
        DEBUG=False,
        JWT_SECRET_KEY="x" * 32,
        DB_PASSWORD="strong-db-password",
        MINIO_SECRET_KEY="strong-minio-password",
        ALLOWED_ORIGINS="https://app.example.com",
    )
    assert settings.cors_origins_list == ["https://app.example.com"]


def test_dashscope_proxy_bypass_is_process_scoped_and_preserves_existing_hosts(monkeypatch):
    monkeypatch.setattr(main.settings, "OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")

    main.configure_provider_proxy_bypass()

    assert "localhost" in main.os.environ["NO_PROXY"]
    assert "dashscope.aliyuncs.com" in main.os.environ["NO_PROXY"]
    assert main.os.environ["no_proxy"] == main.os.environ["NO_PROXY"]
