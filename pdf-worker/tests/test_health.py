def test_health_and_capabilities(client):
    assert client.get("/health").json() == {
        "status": "ok",
        "service": "pdf-worker",
    }
    response = client.get("/capabilities")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database"]["schema_version"] == 5
    assert payload["configuration"]["max_binding_versions"] == 5
    assert all(payload["storage"].values())


def test_uniform_not_found_and_validation_errors(client):
    missing = client.get("/bindings/missing").json()["error"]
    assert missing["code"] == "BINDING_NOT_FOUND"
    invalid = client.post("/bindings").json()["error"]
    assert invalid["code"] == "VALIDATION_ERROR"
