from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from fastapi import UploadFile

from app.models import StoredObject


class StorageBackend(ABC):
    @abstractmethod
    def ensure_directories(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def save_binding_upload(
        self, upload: UploadFile, qr_id: str, max_size_bytes: int
    ) -> StoredObject:
        raise NotImplementedError

    @abstractmethod
    async def save_source_pdf(
        self, upload: UploadFile, job_id: str, max_size_bytes: int
    ) -> StoredObject:
        raise NotImplementedError

    @abstractmethod
    async def save_batch_upload(
        self, upload: UploadFile, batch_key: str, item_key: str, max_size_bytes: int
    ) -> StoredObject:
        raise NotImplementedError

    @abstractmethod
    def commit_batch_upload(self, staging_path: str, qr_id: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def resolve(self, relative_path: str, must_exist: bool = True) -> Path:
        raise NotImplementedError

    @abstractmethod
    def create_output_temp(self, final_relative_path: str) -> Path:
        raise NotImplementedError

    @abstractmethod
    def commit_output_temp(self, temp_path: Path, final_relative_path: str) -> Path:
        raise NotImplementedError

    @abstractmethod
    def discard_temp(self, temp_path: Path) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete(self, relative_path: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def move_to_trash(self, relative_path: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def restore_from_trash(self, trash_path: str, original_path: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def check_directories(self) -> dict[str, bool]:
        raise NotImplementedError
