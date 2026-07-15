from pathlib import Path

from conftest import create_binding


def test_only_five_versions_are_retained_and_files_are_cleaned(client, settings):
    binding = create_binding(client, b"v1")
    qr_id = binding["qr_id"]
    for number in range(2, 8):
        response = client.put(
            f"/bindings/{qr_id}/file",
            files={"file": (f"v{number}.txt", f"v{number}".encode(), "text/plain")},
        )
        assert response.status_code == 200

    versions = client.get(f"/bindings/{qr_id}/versions").json()
    assert [item["version_number"] for item in versions] == [7, 6, 5, 4, 3]
    assert sum(item["is_current"] for item in versions) == 1
    files = [path for path in settings.bindings_dir.rglob("*") if path.is_file()]
    assert len(files) == 5
    assert not list(settings.trash_dir.iterdir())


def test_rollback_and_cross_binding_rejection(client):
    first = create_binding(client, b"v1")
    qr_id = first["qr_id"]
    client.put(
        f"/bindings/{qr_id}/file",
        files={"file": ("v2.txt", b"v2", "text/plain")},
    )
    versions = client.get(f"/bindings/{qr_id}/versions").json()
    old = next(item for item in versions if item["version_number"] == 1)
    rolled_back = client.post(f"/bindings/{qr_id}/rollback/{old['version_id']}")
    assert rolled_back.status_code == 200
    assert rolled_back.json()["current_version"]["version_number"] == 1
    assert client.get(f"/r/{qr_id}").content == b"v1"

    other = create_binding(client, b"other")
    other_version = client.get(f"/bindings/{other['qr_id']}/versions").json()[0]
    rejected = client.post(
        f"/bindings/{qr_id}/rollback/{other_version['version_id']}"
    )
    assert rejected.status_code == 404
    assert rejected.json()["error"]["code"] == "VERSION_NOT_FOUND"


def test_persistence_across_application_recreation(settings):
    from fastapi.testclient import TestClient
    from app.main import create_app

    with TestClient(create_app(settings)) as first_client:
        binding = create_binding(first_client, b"persistent")
    with TestClient(create_app(settings)) as second_client:
        response = second_client.get(f"/r/{binding['qr_id']}")
        assert response.status_code == 200
        assert response.content == b"persistent"
