from conftest import create_binding, create_pdf_job


def test_fixed_entry_stays_on_original_and_cross_binding_is_rejected(client):
    first = create_binding(client, b"original", "answer.txt")
    qr_id = first["qr_id"]
    version_id = first["current_version"]["version_id"]
    fixed_before = client.get(f"/r/{qr_id}/versions/{version_id}")
    assert fixed_before.content == b"original"
    qr = client.get(f"/bindings/{qr_id}/versions/{version_id}/qr.png")
    assert qr.status_code == 200
    client.put(
        f"/bindings/{qr_id}/file",
        files={"file": ("new.txt", b"new", "text/plain")},
    )
    new_version_id = client.get(f"/bindings/{qr_id}").json()["current_version"][
        "version_id"
    ]
    assert client.get(
        f"/bindings/{qr_id}/versions/{new_version_id}/qr.png"
    ).status_code == 200
    assert client.get(f"/r/{qr_id}").content == b"new"
    assert client.get(f"/r/{qr_id}/versions/{version_id}").content == b"original"
    rollback = client.post(f"/bindings/{qr_id}/rollback/{version_id}")
    assert rollback.status_code == 200
    assert client.get(f"/r/{qr_id}").content == b"original"
    assert client.get(f"/r/{qr_id}/versions/{new_version_id}").content == b"new"
    versions = client.get(f"/bindings/{qr_id}/versions").json()
    assert next(item for item in versions if item["version_id"] == version_id)["is_pinned"]

    other = create_binding(client, b"other")
    other_version = other["current_version"]["version_id"]
    assert client.get(f"/r/{qr_id}/versions/{other_version}").status_code == 404


def test_pinned_version_survives_cleanup(client, settings):
    binding = create_binding(client, b"v1")
    qr_id = binding["qr_id"]
    pinned_id = binding["current_version"]["version_id"]
    client.get(f"/bindings/{qr_id}/versions/{pinned_id}/qr.png")
    for number in range(2, 9):
        client.put(
            f"/bindings/{qr_id}/file",
            files={"file": (f"v{number}.txt", f"v{number}".encode(), "text/plain")},
        )
    versions = client.get(f"/bindings/{qr_id}/versions").json()
    assert any(item["version_id"] == pinned_id and item["is_pinned"] for item in versions)
    assert len([item for item in versions if not item["is_pinned"]]) == 5
    assert client.get(f"/r/{qr_id}/versions/{pinned_id}").content == b"v1"
    assert len([path for path in settings.bindings_dir.rglob("*") if path.is_file()]) == 6


def test_fixed_pdf_job_pins_current_version(client):
    binding = create_binding(client)
    response = create_pdf_job(client, binding["qr_id"], qr_mode="fixed")
    assert response.status_code == 201, response.text
    job = response.json()
    assert job["qr_mode"] == "fixed"
    assert job["qr_version_id"] == binding["current_version"]["version_id"]
    versions = client.get(f"/bindings/{binding['qr_id']}/versions").json()
    assert versions[0]["is_pinned"] is True
