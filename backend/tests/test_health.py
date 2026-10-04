def test_health_check(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 200
    assert body["message"] == "ok"
    assert body["data"]["status"] == "healthy"
    assert body["data"]["app_name"]


def test_health_detail_returns_service_statuses(client):
    response = client.get("/api/health/detail")

    assert response.status_code == 200
    services = response.json()["data"]["services"]
    assert {"database", "redis", "minio"} <= set(services)
