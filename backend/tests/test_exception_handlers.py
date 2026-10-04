from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from sqlalchemy.exc import OperationalError

from app.core.exceptions import register_exception_handlers
from app.middleware.request_logger import RequestLogMiddleware


def test_validation_error_uses_stable_contract():
    app = FastAPI()
    app.add_middleware(RequestLogMiddleware)
    register_exception_handlers(app)

    class Payload(BaseModel):
        epochs: int = Field(ge=10)

    @app.post("/training")
    def create_training(payload: Payload):
        return payload

    response = TestClient(app).post("/training", json={"epochs": 1})

    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_ERROR"
    assert response.json()["request_id"]
    assert response.headers["x-request-id"] == response.json()["request_id"]


def test_validation_error_redacts_sensitive_input():
    app = FastAPI()
    app.add_middleware(RequestLogMiddleware)
    register_exception_handlers(app)

    class Payload(BaseModel):
        password: str = Field(min_length=12)

    @app.post("/login")
    def login(payload: Payload):
        return payload

    response = TestClient(app).post("/login", json={"password": "too-short"})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail[0]["input"] == "[redacted]"
    assert "too-short" not in str(response.json())


def test_not_found_uses_the_same_error_contract():
    app = FastAPI()
    app.add_middleware(RequestLogMiddleware)
    register_exception_handlers(app)

    response = TestClient(app).get("/missing")

    assert response.status_code == 404
    assert response.json()["error_code"] == "HTTP_404"
    assert response.json()["detail"]["code"] == "HTTP_404"
    assert response.headers["x-request-id"] == response.json()["request_id"]


def test_database_outage_is_retryable_and_does_not_leak_driver_detail():
    app = FastAPI()
    app.add_middleware(RequestLogMiddleware)
    register_exception_handlers(app)

    @app.get("/db")
    def database_call():
        raise OperationalError("connection failed", {}, RuntimeError("private driver detail"))

    response = TestClient(app).get("/db")

    assert response.status_code == 503
    assert response.json()["error_code"] == "DATABASE_UNAVAILABLE"
    assert response.json()["retryable"] is True
    assert "private driver detail" not in response.text
