from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.config import Settings
from app.errors import AppError, UploadTooLargeError
from app.models import StoredObject
from app.storage.base import StorageBackend


logger = logging.getLogger(__name__)
CHUNK_SIZE = 1024 * 1024


def safe_display_filename(filename: str | None) -> str:
    value = (filename or "upload.bin").replace("\\", "/").split("/")[-1]
    value = "".join(ch for ch in value if ch >= " " and ch != "\x7f").strip()
    return (value or "upload.bin")[:255]


class LocalStorageBackend(StorageBackend):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = settings.storage_root.resolve()

    def ensure_directories(self) -> None:
        self.settings.ensure_directories()

    def _relative(self, path: Path) -> str:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise AppError(500, "STORAGE_PATH_INVALID", "storage path is invalid")
        return resolved.relative_to(self.root).as_posix()

    def resolve(self, relative_path: str, must_exist: bool = True) -> Path:
        if not relative_path or Path(relative_path).is_absolute():
            raise AppError(500, "STORAGE_PATH_INVALID", "storage path is invalid")
        unresolved = self.root / relative_path
        current = self.root
        for part in Path(relative_path).parts:
            if part in {"", ".", ".."}:
                raise AppError(500, "STORAGE_PATH_INVALID", "storage path is invalid")
            current = current / part
            if current.is_symlink():
                raise AppError(500, "STORAGE_PATH_INVALID", "storage path is invalid")
        candidate = unresolved.resolve(strict=False)
        if not candidate.is_relative_to(self.root):
            raise AppError(500, "STORAGE_PATH_INVALID", "storage path is invalid")
        if must_exist and not candidate.is_file():
            raise AppError(409, "STORED_FILE_MISSING", "stored file is unavailable")
        return candidate

    async def _save_upload(
        self,
        upload: UploadFile,
        final_path: Path,
        max_size_bytes: int,
    ) -> StoredObject:
        final_path.parent.mkdir(parents=True, exist_ok=True)
        self._relative(final_path)
        original_filename = safe_display_filename(upload.filename)
        mime_type = (upload.content_type or "application/octet-stream").split(";")[0]
        digest = hashlib.sha256()
        size = 0
        temp_path: Path | None = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=".upload-", dir=final_path.parent, delete=False
            ) as temp_file:
                temp_path = Path(temp_file.name)
                while chunk := await upload.read(CHUNK_SIZE):
                    size += len(chunk)
                    if size > max_size_bytes:
                        raise UploadTooLargeError(self.settings.max_upload_size_mb)
                    digest.update(chunk)
                    temp_file.write(chunk)
                if size == 0:
                    raise AppError(400, "EMPTY_FILE", "uploaded file is empty")
                temp_file.flush()
                os.fsync(temp_file.fileno())

            if final_path.exists():
                raise AppError(409, "STORAGE_COLLISION", "storage name collision")
            os.replace(temp_path, final_path)
            temp_path = None
            return StoredObject(
                relative_path=self._relative(final_path),
                stored_filename=final_path.name,
                original_filename=original_filename,
                mime_type=mime_type,
                size_bytes=size,
                sha256=digest.hexdigest(),
            )
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            await upload.close()

    async def save_binding_upload(
        self, upload: UploadFile, qr_id: str, max_size_bytes: int
    ) -> StoredObject:
        final_path = self.settings.bindings_dir / qr_id / f"{uuid.uuid4().hex}.bin"
        return await self._save_upload(upload, final_path, max_size_bytes)

    async def save_source_pdf(
        self, upload: UploadFile, job_id: str, max_size_bytes: int
    ) -> StoredObject:
        final_path = self.settings.source_pdfs_dir / f"{job_id}.pdf"
        return await self._save_upload(upload, final_path, max_size_bytes)

    def create_output_temp(self, final_relative_path: str) -> Path:
        final_path = self.resolve(final_relative_path, must_exist=False)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(prefix=".output-", dir=final_path.parent)
        os.close(handle)
        return Path(name)

    def commit_output_temp(self, temp_path: Path, final_relative_path: str) -> Path:
        final_path = self.resolve(final_relative_path, must_exist=False)
        if temp_path.parent.resolve() != final_path.parent.resolve():
            raise AppError(500, "STORAGE_PATH_INVALID", "temporary path is invalid")
        if final_path.exists():
            raise AppError(409, "STORAGE_COLLISION", "storage name collision")
        os.replace(temp_path, final_path)
        return final_path

    def discard_temp(self, temp_path: Path) -> None:
        temp_path.unlink(missing_ok=True)

    def delete(self, relative_path: str) -> None:
        path = self.resolve(relative_path, must_exist=False)
        path.unlink(missing_ok=True)

    def move_to_trash(self, relative_path: str) -> str:
        original = self.resolve(relative_path)
        trash = self.settings.trash_dir / f"{uuid.uuid4().hex}.trash"
        os.replace(original, trash)
        return self._relative(trash)

    def restore_from_trash(self, trash_path: str, original_path: str) -> None:
        trash = self.resolve(trash_path)
        original = self.resolve(original_path, must_exist=False)
        original.parent.mkdir(parents=True, exist_ok=True)
        os.replace(trash, original)

    @staticmethod
    def _check_write(path: Path) -> bool:
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", prefix=".capability-", dir=path, delete=True
            ) as probe:
                probe.write("ok")
                probe.flush()
            return True
        except OSError:
            return False

    def check_directories(self) -> dict[str, bool]:
        return {
            "storage_root_exists": self.settings.storage_root.is_dir(),
            "bindings_writeable": self._check_write(self.settings.bindings_dir),
            "source_pdfs_writeable": self._check_write(
                self.settings.source_pdfs_dir
            ),
            "generated_pdfs_writeable": self._check_write(
                self.settings.generated_pdfs_dir
            ),
        }
