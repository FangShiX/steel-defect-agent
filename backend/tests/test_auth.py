def test_register_user(client):
    response = client.post(
        "/api/auth/register",
        json={
            "username": "alice",
            "email": "alice@example.com",
            "password": "password123",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "alice"
    assert body["email"] == "alice@example.com"
    assert "hashed_password" not in body


def test_login_user(client):
    client.post(
        "/api/auth/register",
        json={
            "username": "bob",
            "email": "bob@example.com",
            "password": "password123",
        },
    )

    response = client.post(
        "/api/auth/login",
        json={"username": "bob", "password": "password123"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["username"] == "bob"


def test_login_rejects_wrong_password(client):
    client.post(
        "/api/auth/register",
        json={
            "username": "carol",
            "email": "carol@example.com",
            "password": "password123",
        },
    )

    response = client.post(
        "/api/auth/login",
        json={"username": "carol", "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == 401
