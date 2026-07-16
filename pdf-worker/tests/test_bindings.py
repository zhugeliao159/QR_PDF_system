from io import BytesIO

from PIL import Image

from conftest import create_binding, png_bytes, prepare_preview


def current_bytes(client, token):
    resolved = client.app.state.resolver_service.resolve_latest(token)
    return client.app.state.asset_service.path(resolved.asset).read_bytes()


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

    prepare_preview(client, binding["qr_id"])
    file_response = client.get(f"/r/{binding['qr_id']}", follow_redirects=False)
    assert file_response.status_code == 307
    preview = client.get(file_response.headers["location"])
    assert preview.status_code == 200
    assert "内容仅供在线预览" in preview.text


def test_replace_keeps_qr_id_and_failed_replace_keeps_current(client):
    binding = create_binding(client, b"first")
    qr_id = binding["qr_id"]
    replaced = client.put(
        f"/bindings/{qr_id}/file",
        files={"file": ("second.txt", b"second", "text/plain")},
    )
    assert replaced.status_code == 200
    assert replaced.json()["qr_id"] == qr_id
    assert current_bytes(client, qr_id) == b"second"

    rejected = client.put(
        f"/bindings/{qr_id}/file",
        files={"file": ("broken.png", b"not-an-image", "image/png")},
    )
    assert rejected.status_code == 415
    assert rejected.json()["error"]["code"] == "INVALID_IMAGE_FILE"
    assert current_bytes(client, qr_id) == b"second"
    assert len(client.get(f"/bindings/{qr_id}/versions").json()) == 2


def test_public_base_url_is_used_by_qr_service(client):
    binding = create_binding(client)
    service = client.app.state.qr_service
    assert service.qr_url(binding["qr_id"]) == binding["qr_url"]
