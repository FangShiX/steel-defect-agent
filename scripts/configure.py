"""Create deployment configuration with unique secrets; never overwrite it."""
import argparse
from pathlib import Path
import secrets
from urllib.parse import urlparse


def configure(output: Path, production: bool, origin: str) -> None:
    parsed = urlparse(origin)
    if production and (parsed.scheme != "https" or not parsed.netloc or parsed.hostname in {"localhost", "127.0.0.1"}):
        raise ValueError("Production requires an explicit HTTPS origin")
    db_password = secrets.token_urlsafe(32)
    minio_password = secrets.token_urlsafe(32)
    values = {
        "POSTGRES_DB": "ssdd_agent", "POSTGRES_USER": "ssdd_app", "POSTGRES_PASSWORD": db_password,
        "DB_HOST": "postgres", "DB_NAME": "ssdd_agent", "DB_USER": "ssdd_app", "DB_PASSWORD": db_password,
        "REDIS_HOST": "redis", "MINIO_ENDPOINT": "minio:9000", "MINIO_ROOT_USER": "ssdd_minio",
        "MINIO_ROOT_PASSWORD": minio_password, "MINIO_ACCESS_KEY": "ssdd_minio", "MINIO_SECRET_KEY": minio_password,
        "MINIO_BUCKET": "ssdd-images", "MINIO_SECURE": "false", "JWT_SECRET_KEY": secrets.token_urlsafe(48),
        "BOOTSTRAP_ADMIN_PASSWORD": secrets.token_urlsafe(20), "BOOTSTRAP_ADMIN_EMAIL": "admin@example.com",
        "OPENAI_API_KEY": "", "OPENAI_BASE_URL": "https://api.openai.com/v1", "OPENAI_MODEL": "gpt-4o-mini",
        "EMBEDDING_API_KEY": "", "EMBEDDING_BASE_URL": "", "EMBEDDING_MODEL": "",
        "ALLOWED_ORIGINS": origin, "PASSWORD_RESET_URL": origin + "/login", "APP_PORT": "8080",
        "DEBUG": str(not production).lower(), "DATASET_BASE_DIR": "/app/datasets", "TRAIN_OUTPUT_DIR": "/app/runs/train",
    }
    # Exclusive creation prevents accidental replacement of running credentials.
    with output.open("x", encoding="utf-8", newline="\n") as file:
        file.write("# Private deployment configuration. Never commit or share.\n")
        file.write("\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
    print(f"Created {output.name}. Read BOOTSTRAP_ADMIN_PASSWORD locally to sign in as admin.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--origin", default="http://localhost:8080")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    configure(args.output or Path(".env.production" if args.production else ".env"), args.production, args.origin)
