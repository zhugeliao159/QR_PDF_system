from io import BytesIO

from PIL import Image

from conftest import create_binding, png_bytes


def test_create_qr_and_permanent_file(client):
    binding = create_binding(client, png_bytes(), "answer.png")
    assert len(binding["qr_id"]) == 32
    assert binding["qr_url"] == f"http://test.local:18081/q/{binding['qr_id']}"
    assert binding["qr_png_url"].endswith(f"/bindings/{binding['qr_id']}/qr.png")
    assert binding["version_count"] == 1
    assert len(binding["sha256"]) == 64

    qr_response = client.get(f"/bindings/{binding['qr_id']}/qr.png")
    assert qr_response.status_code == 200
    assert qr_response.headers["content-type"] == "image/png"
    with Image.open(BytesIO(qr_response.content)) as qr_image:
        assert qr_image.format == "PNG"
        assert qr_image.width == qr_image.height

    file_response = client.get(f"/r/{binding['qr_id']}")
    assert file_response.status_code == 200
    assert file_response.content == png_bytes()
    assert file_response.headers["cache-control"].startswith("no-cache")


def test_replace_keeps_qr_id_and_failed_replace_keeps_current(client):
    binding = create_binding(client, b"first")
    qr_id = binding["qr_id"]
    replaced = client.put(
        f"/bindings/{qr_id}/file",
        files={"file": ("second.txt", b"second", "text/plain")},
    )
    assert replaced.status_code == 200
    assert replaced.json()["qr_id"] == qr_id
    assert client.get(f"/r/{qr_id}").content == b"second"

    rejected = client.put(
        f"/bindings/{qr_id}/file",
        files={"file": ("broken.png", b"not-an-image", "image/png")},
    )
    assert rejected.status_code == 415
    assert rejected.json()["error"]["code"] == "INVALID_IMAGE_FILE"
    assert client.get(f"/r/{qr_id}").content == b"second"
    assert len(client.get(f"/bindings/{qr_id}/versions").json()) == 2


def test_public_base_url_is_used_by_qr_service(client):
    binding = create_binding(client)
    service = client.app.state.qr_service
    assert service.qr_url(binding["qr_id"]) == binding["qr_url"]
