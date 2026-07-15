import pytest

from app.errors import AppError


def test_storage_rejects_traversal_and_symlink(client, settings, tmp_path):
    storage = client.app.state.storage
    with pytest.raises(AppError, match="storage path is invalid"):
        storage.resolve("../outside.txt", must_exist=False)

    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = settings.bindings_dir / "linked.txt"
    link.symlink_to(outside)
    with pytest.raises(AppError, match="storage path is invalid"):
        storage.resolve("bindings/linked.txt")
