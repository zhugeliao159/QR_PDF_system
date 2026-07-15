from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import fitz
from fastapi import UploadFile

from app.config import Settings
from app.database import Database
from app.errors import AppError
from app.models import StoredObject, utc_now_iso
from app.services.binding_service import BindingService
from app.services.qr_service import QrService
from app.storage.base import StorageBackend


logger = logging.getLogger(__name__)
MM_TO_POINTS = 72.0 / 25.4
POSITIONS = {"top-left", "top-right", "bottom-left", "bottom-right"}
MIN_QR_SIZE_MM = 10.0
MAX_QR_SIZE_MM = 50.0
MIN_MARGIN_MM = 0.0
MAX_MARGIN_MM = 50.0


class PdfService:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        storage: StorageBackend,
        binding_service: BindingService,
        qr_service: QrService,
    ) -> None:
        self.settings = settings
        self.database = database
        self.storage = storage
        self.binding_service = binding_service
        self.qr_service = qr_service

    @staticmethod
    def _validate_parameters(
        page: int, position: str, size_mm: float, margin_mm: float
    ) -> None:
        if page < 1:
            raise AppError(
                422, "PDF_PAGE_OUT_OF_RANGE", "page must be greater than or equal to 1"
            )
        if position not in POSITIONS:
            raise AppError(
                422,
                "INVALID_QR_POSITION",
                "position must be one of top-left, top-right, bottom-left, bottom-right",
            )
        if not MIN_QR_SIZE_MM <= size_mm <= MAX_QR_SIZE_MM:
            raise AppError(
                422,
                "INVALID_QR_SIZE",
                f"size_mm must be between {MIN_QR_SIZE_MM:g} and {MAX_QR_SIZE_MM:g}",
            )
        if not MIN_MARGIN_MM <= margin_mm <= MAX_MARGIN_MM:
            raise AppError(
                422,
                "INVALID_QR_MARGIN",
                f"margin_mm must be between {MIN_MARGIN_MM:g} and {MAX_MARGIN_MM:g}",
            )

    @staticmethod
    def _visual_qr_rect(
        page: fitz.Page, position: str, size_mm: float, margin_mm: float
    ) -> fitz.Rect:
        page_rect = fitz.Rect(page.rect)
        size = size_mm * MM_TO_POINTS
        margin = margin_mm * MM_TO_POINTS
        if size + 2 * margin > page_rect.width or size + 2 * margin > page_rect.height:
            raise AppError(
                422,
                "QR_DOES_NOT_FIT_PAGE",
                "QR code and margins do not fit on the selected page",
                {
                    "page_width_pt": round(page_rect.width, 2),
                    "page_height_pt": round(page_rect.height, 2),
                },
            )

        if position.endswith("left"):
            x0 = page_rect.x0 + margin
        else:
            x0 = page_rect.x1 - margin - size
        if position.startswith("top"):
            y0 = page_rect.y0 + margin
        else:
            y0 = page_rect.y1 - margin - size

        visual_rect = fitz.Rect(x0, y0, x0 + size, y0 + size)
        insert_rect = visual_rect * page.derotation_matrix
        insert_rect.normalize()
        return insert_rect

    @staticmethod
    def _sha256(path: Path) -> tuple[int, str]:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
        return size, digest.hexdigest()

    def _validate_source_pdf(self, stored: StoredObject) -> None:
        path = self.storage.resolve(stored.relative_path)
        suffix = Path(stored.original_filename).suffix.lower()
        if suffix != ".pdf":
            raise AppError(415, "PDF_EXTENSION_REQUIRED", "uploaded file must use .pdf")
        if stored.mime_type not in {"application/pdf", "application/octet-stream"}:
            raise AppError(
                415, "PDF_MIME_TYPE_REQUIRED", "uploaded file must use a PDF MIME type"
            )
        with path.open("rb") as stream:
            if not stream.read(5).startswith(b"%PDF-"):
                raise AppError(422, "INVALID_PDF_FILE", "file does not contain a PDF header")

    def _stamp_pdf(
        self,
        source: StoredObject,
        qr_id: str,
        job_id: str,
        page_number: int,
        position: str,
        size_mm: float,
        margin_mm: float,
        qr_url: str,
    ) -> tuple[str, int, str]:
        source_path = self.storage.resolve(source.relative_path)
        output_relative = f"generated-pdfs/{job_id}.pdf"
        temp_path = self.storage.create_output_temp(output_relative)
        original_page_count = 0

        try:
            try:
                document = fitz.open(source_path)
            except Exception as exc:
                raise AppError(422, "INVALID_PDF_FILE", "PDF cannot be opened") from exc

            with document:
                if document.needs_pass or document.is_encrypted:
                    raise AppError(
                        422, "PDF_ENCRYPTED", "encrypted or password-protected PDF is unsupported"
                    )
                original_page_count = document.page_count
                if original_page_count <= 0:
                    raise AppError(422, "EMPTY_PDF", "PDF has no pages")
                if original_page_count > self.settings.max_pdf_pages:
                    raise AppError(
                        422,
                        "PDF_TOO_MANY_PAGES",
                        f"PDF exceeds the {self.settings.max_pdf_pages} page limit",
                    )
                if page_number > original_page_count:
                    raise AppError(
                        422,
                        "PDF_PAGE_OUT_OF_RANGE",
                        f"page must be between 1 and {original_page_count}",
                        {"page_count": original_page_count},
                    )

                page = document.load_page(page_number - 1)
                insert_rect = self._visual_qr_rect(
                    page, position, size_mm, margin_mm
                )
                page.insert_image(
                    insert_rect,
                    stream=self.qr_service.png_for_url(qr_url),
                    overlay=True,
                    keep_proportion=False,
                )
                document.save(temp_path, garbage=4, deflate=True)

            if not temp_path.is_file() or temp_path.stat().st_size == 0:
                raise AppError(500, "PDF_OUTPUT_EMPTY", "PDF output was not created")
            try:
                with fitz.open(temp_path) as verification:
                    if verification.needs_pass or verification.page_count != original_page_count:
                        raise AppError(
                            500, "PDF_OUTPUT_INVALID", "generated PDF failed validation"
                        )
            except AppError:
                raise
            except Exception as exc:
                raise AppError(
                    500, "PDF_OUTPUT_INVALID", "generated PDF cannot be reopened"
                ) from exc

            with temp_path.open("rb") as stream:
                os.fsync(stream.fileno())
            output_size, output_sha256 = self._sha256(temp_path)
            self.storage.commit_output_temp(temp_path, output_relative)
            return output_relative, output_size, output_sha256
        except Exception:
            self.storage.discard_temp(temp_path)
            raise

    def _insert_processing_job(
        self,
        job_id: str,
        binding_id: int,
        source: StoredObject,
        page: int,
        position: str,
        size_mm: float,
        margin_mm: float,
        created_at: str,
        qr_mode: str,
        qr_version_id: int | None,
    ) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO pdf_jobs
                    (job_id, binding_id, qr_mode, qr_version_id,
                     source_original_filename, source_storage_path,
                     page_number, position, size_mm, margin_mm, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'processing', ?)
                """,
                (
                    job_id,
                    binding_id,
                    qr_mode,
                    qr_version_id,
                    source.original_filename,
                    source.relative_path,
                    page,
                    position,
                    size_mm,
                    margin_mm,
                    created_at,
                ),
            )

    def _set_failed(self, job_id: str, code: str, message: str) -> None:
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    """
                    UPDATE pdf_jobs
                    SET status = 'failed', error_code = ?, error_message = ?,
                        completed_at = ?
                    WHERE job_id = ?
                    """,
                    (code, message, utc_now_iso(), job_id),
                )
        except Exception:
            logger.exception("database error while marking PDF job failed job_id=%s", job_id)

    async def create_job(
        self,
        upload: UploadFile,
        qr_id: str,
        page: int,
        position: str,
        size_mm: float,
        margin_mm: float,
        qr_mode: str = "dynamic",
    ) -> dict[str, Any]:
        self._validate_parameters(page, position, size_mm, margin_mm)
        if qr_mode not in {"dynamic", "fixed"}:
            raise AppError(422, "INVALID_QR_MODE", "qr_mode must be dynamic or fixed")
        binding = self.binding_service._binding_row(qr_id)
        qr_version_id = int(binding["version_id"]) if qr_mode == "fixed" else None
        qr_url = (
            self.qr_service.fixed_url(qr_id, qr_version_id)
            if qr_version_id is not None
            else self.qr_service.qr_url(qr_id)
        )
        job_id = uuid.uuid4().hex
        source = await self.storage.save_source_pdf(
            upload, job_id, self.settings.max_upload_size_bytes
        )
        inserted = False
        output_relative: str | None = None

        try:
            created_at = utc_now_iso()
            self._insert_processing_job(
                job_id,
                binding["id"],
                source,
                page,
                position,
                size_mm,
                margin_mm,
                created_at,
                qr_mode,
                qr_version_id,
            )
            inserted = True
            self._validate_source_pdf(source)
            output_relative, output_size, output_sha256 = self._stamp_pdf(
                source,
                qr_id,
                job_id,
                page,
                position,
                size_mm,
                margin_mm,
                qr_url,
            )
            with self.database.transaction() as connection:
                connection.execute(
                    """
                    UPDATE pdf_jobs
                    SET status = 'completed', output_storage_path = ?,
                        output_size_bytes = ?, output_sha256 = ?, completed_at = ?
                    WHERE job_id = ?
                    """,
                    (
                        output_relative,
                        output_size,
                        output_sha256,
                        utc_now_iso(),
                        job_id,
                    ),
                )
                if qr_version_id is not None:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO version_references
                            (version_id, reference_type, source_job_id, created_at)
                        VALUES (?, 'pdf_job', ?, ?)
                        """,
                        (qr_version_id, job_id, utc_now_iso()),
                    )
        except AppError as exc:
            if output_relative is not None:
                self.storage.delete(output_relative)
            if inserted:
                self._set_failed(job_id, exc.code, exc.message)
                exc.details = {**exc.details, "job_id": job_id}
            else:
                self.storage.delete(source.relative_path)
            logger.warning("PDF job rejected job_id=%s code=%s", job_id, exc.code)
            raise
        except Exception as exc:
            if output_relative is not None:
                self.storage.delete(output_relative)
            if inserted:
                self._set_failed(job_id, "PDF_PROCESSING_FAILED", "PDF processing failed")
            else:
                self.storage.delete(source.relative_path)
            logger.exception("PDF job failed job_id=%s", job_id)
            raise AppError(
                500,
                "PDF_PROCESSING_FAILED",
                "PDF processing failed",
                {"job_id": job_id} if inserted else {},
            ) from exc

        logger.info("PDF job completed job_id=%s qr_id=%s", job_id, qr_id)
        return self.get_job(job_id)

    def _job_row(self, job_id: str) -> sqlite3.Row:
        with self.database.read() as connection:
            row = connection.execute(
                """
                SELECT j.*, b.qr_id
                FROM pdf_jobs j
                JOIN bindings b ON b.id = j.binding_id
                WHERE j.job_id = ?
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            raise AppError(404, "PDF_JOB_NOT_FOUND", "PDF job does not exist")
        return row

    def get_job(self, job_id: str) -> dict[str, Any]:
        row = self._job_row(job_id)
        download_url = None
        if row["status"] == "completed":
            download_url = (
                f"{self.settings.public_base_url}/pdf/jobs/{job_id}/download"
            )
        return {
            "job_id": row["job_id"],
            "status": row["status"],
            "qr_id": row["qr_id"],
            "source_filename": row["source_original_filename"],
            "page": row["page_number"],
            "position": row["position"],
            "size_mm": row["size_mm"],
            "margin_mm": row["margin_mm"],
            "download_url": download_url,
            "output_size_bytes": row["output_size_bytes"],
            "output_sha256": row["output_sha256"],
            "error_code": row["error_code"],
            "error_message": row["error_message"],
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
            "qr_mode": row["qr_mode"],
            "qr_version_id": row["qr_version_id"],
        }

    def download(self, job_id: str) -> tuple[Path, str]:
        row = self._job_row(job_id)
        if row["status"] != "completed" or not row["output_storage_path"]:
            raise AppError(409, "PDF_JOB_NOT_COMPLETED", "PDF job has no downloadable output")
        path = self.storage.resolve(row["output_storage_path"])
        stem = Path(row["source_original_filename"]).stem[:200] or "output"
        return path, f"{stem}_with_qr.pdf"

    def preview_png(self, job_id: str) -> bytes:
        row = self._job_row(job_id)
        if row["status"] != "completed" or not row["output_storage_path"]:
            raise AppError(409, "PDF_JOB_NOT_COMPLETED", "PDF job has no preview")
        path = self.storage.resolve(row["output_storage_path"])
        try:
            with fitz.open(path) as document:
                page = document.load_page(int(row["page_number"]) - 1)
                pixmap = page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2), alpha=False)
                return pixmap.tobytes("png")
        except AppError:
            raise
        except Exception as exc:
            raise AppError(500, "PDF_PREVIEW_FAILED", "PDF preview failed") from exc

    def list_recent(self, limit: int = 6) -> list[dict[str, Any]]:
        with self.database.read() as connection:
            rows = connection.execute(
                """
                SELECT j.*, b.qr_id, b.title, b.display_code
                FROM pdf_jobs j JOIN bindings b ON b.id = j.binding_id
                ORDER BY j.created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
