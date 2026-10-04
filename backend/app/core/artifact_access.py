"""Access control for short-lived Agent artifacts."""

from contextvars import ContextVar


artifact_owner_id: ContextVar[int | None] = ContextVar("artifact_owner_id", default=None)
_artifact_owners: dict[str, int] = {}


def register_artifact(filename: str) -> None:
    owner_id = artifact_owner_id.get()
    if owner_id is not None:
        _artifact_owners[filename] = owner_id


def can_read_artifact(filename: str, user_id: int, is_superuser: bool = False) -> bool:
    owner_id = _artifact_owners.get(filename)
    return owner_id is not None and (is_superuser or owner_id == user_id)


def unregister_artifact(filename: str) -> None:
    _artifact_owners.pop(filename, None)
