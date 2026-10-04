from types import SimpleNamespace

from app.entity.db_models import EMBEDDING_DIM
from app.services.embedding_service import embedding_service


def test_embedding_request_keeps_the_pgvector_dimension(monkeypatch):
    calls = []

    class FakeEmbeddings:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(data=[SimpleNamespace(embedding=[0.25] * EMBEDDING_DIM)])

    fake_client = SimpleNamespace(embeddings=FakeEmbeddings())
    monkeypatch.setattr(embedding_service, "_get_client", lambda: fake_client)

    result = embedding_service.embed_text("RAG dimension contract")

    assert len(result) == EMBEDDING_DIM
    assert calls[0]["dimensions"] == EMBEDDING_DIM
    assert calls[0]["input"] == ["RAG dimension contract"]
