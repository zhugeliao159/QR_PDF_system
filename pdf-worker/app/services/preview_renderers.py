from __future__ import annotations

import hashlib
import warnings
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Callable, Protocol

import fitz
from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import Settings
from app.errors import AppError


ALLOWED_IMAGE_FORMATS = {"PNG", "JPEG", "WEBP"}


@dataclass(frozen=True)
class PreviewRenderConfig:
    dpi: int
    webp_quality: int
    webp_method: int
    max_pages: int
    max_render_width: int
    renderer_version: str

    @classmethod
    def from_settings(cls, settings: Settings) -> "PreviewRenderConfig":
        return cls(
            dpi=settings.preview_dpi,
            webp_quality=settings.preview_webp_quality,
            webp_method=settings.preview_webp_method,
            max_pages=settings.preview_max_pages,
            max_render_width=settings.preview_max_render_width,
            renderer_version=settings.preview_render_version,
        )

    def as_dict(self) -> dict[str, int | str]:
        return {
            "dpi": self.dpi,
            "webp_quality": self.webp_quality,
            "webp_method": self.webp_method,
            "max_pages": self.max_pages,
            "max_render_width": self.max_render_width,
            "renderer_version": self.renderer_version,
        }


@dataclass(frozen=True)
class PreviewPageMetadata:
    page_number: int
    filename: str
    width: int
    height: int
    size_bytes: int
    sha256: str
    mime_type: str = "image/webp"


@dataclass(frozen=True)
class PreviewRenderResult:
    pages: tuple[PreviewPageMetadata, ...]
    total_size_bytes: int


class PreviewRenderer(Protocol):
    def render(
        self,
        source_path: Path,
        output_dir: Path,
        config: PreviewRenderConfig,
        progress: Callable[[int, int], None] | None = None,
    ) -> PreviewRenderResult:
        """Create validated WebP preview pages in an empty temporary directory."""


def _validate_webp(path: Path, page_number: int) -> PreviewPageMetadata:
    try:
        with Image.open(path) as image:
            image.load()
            if image.format != "WEBP":
                raise AppError(422, "PREVIEW_WEBP_INVALID", "preview output is not WebP")
            width, height = image.size
    except AppError:
        raise
    except (OSError, UnidentifiedImageError) as exc:
        raise AppError(422, "PREVIEW_WEBP_INVALID", "preview output cannot be opened") from exc
    if width <= 0 or height <= 0 or path.stat().st_size <= 0:
        raise AppError(422, "PREVIEW_PAGE_INVALID", "preview page is empty or invalid")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return PreviewPageMetadata(
        page_number=page_number,
        filename=path.name,
        width=width,
        height=height,
        size_bytes=path.stat().st_size,
        sha256=digest.hexdigest(),
    )


def _write_webp(image: Image.Image, path: Path, config: PreviewRenderConfig) -> None:
    image.save(
        path,
        format="WEBP",
        quality=config.webp_quality,
        method=config.webp_method,
    )


class PdfPreviewRenderer:
    def render(
        self,
        source_path: Path,
        output_dir: Path,
        config: PreviewRenderConfig,
        progress: Callable[[int, int], None] | None = None,
    ) -> PreviewRenderResult:
        try:
            document = fitz.open(source_path)
        except Exception as exc:
            raise AppError(422, "PREVIEW_PDF_INVALID", "PDF cannot be opened") from exc
        pages: list[PreviewPageMetadata] = []
        try:
            if document.needs_pass:
                raise AppError(
                    422,
                    "PREVIEW_PDF_ENCRYPTED",
                    "encrypted PDF files cannot be rendered as previews",
                )
            page_count = document.page_count
            if page_count <= 0:
                raise AppError(422, "PREVIEW_PDF_EMPTY", "PDF has no pages")
            if page_count > config.max_pages:
                raise AppError(
                    413,
                    "PREVIEW_PDF_PAGE_LIMIT",
                    "PDF page count exceeds the preview limit",
                )
            matrix = fitz.Matrix(config.dpi / 72, config.dpi / 72)
            for page_number in range(1, page_count + 1):
                page = document.load_page(page_number - 1)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                try:
                    with BytesIO(pixmap.tobytes("png")) as raw:
                        with Image.open(raw) as rendered:
                            rendered.load()
                            preview = rendered.convert("RGB")
                    try:
                        if preview.width > config.max_render_width:
                            preview.thumbnail(
                                (config.max_render_width, preview.height),
                                Image.Resampling.LANCZOS,
                            )
                        output = output_dir / f"page-{page_number:04d}.webp"
                        _write_webp(preview, output, config)
                    finally:
                        preview.close()
                finally:
                    pixmap = None
                    page = None
                pages.append(_validate_webp(output, page_number))
                if progress is not None:
                    progress(page_count, len(pages))
        except AppError:
            raise
        except Exception as exc:
            raise AppError(422, "PREVIEW_PDF_RENDER_FAILED", "PDF preview rendering failed") from exc
        finally:
            document.close()
        return PreviewRenderResult(
            pages=tuple(pages), total_size_bytes=sum(page.size_bytes for page in pages)
        )


class ImagePreviewRenderer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def render(
        self,
        source_path: Path,
        output_dir: Path,
        config: PreviewRenderConfig,
        progress: Callable[[int, int], None] | None = None,
    ) -> PreviewRenderResult:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(source_path) as source:
                    source.load()
                    if source.format not in ALLOWED_IMAGE_FORMATS:
                        raise AppError(
                            415,
                            "PREVIEW_IMAGE_FORMAT_INVALID",
                            "image format is not supported for previews",
                        )
                    width, height = source.size
                    if width <= 0 or height <= 0:
                        raise AppError(
                            422,
                            "PREVIEW_IMAGE_DIMENSIONS_INVALID",
                            "image dimensions are invalid",
                        )
                    if width * height > self.settings.max_image_pixels:
                        raise AppError(
                            413,
                            "PREVIEW_IMAGE_PIXELS_EXCEEDED",
                            "image pixel count exceeds the preview limit",
                        )
                    normalized = ImageOps.exif_transpose(source).copy()
            try:
                has_alpha = "A" in normalized.getbands() or (
                    normalized.mode == "P" and "transparency" in normalized.info
                )
                if has_alpha:
                    rgba = normalized.convert("RGBA")
                    try:
                        preview = Image.new("RGB", rgba.size, "white")
                        preview.paste(rgba, mask=rgba.getchannel("A"))
                    finally:
                        rgba.close()
                else:
                    preview = normalized.convert("RGB")
            finally:
                normalized.close()
        except AppError:
            raise
        except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
            raise AppError(
                413,
                "PREVIEW_IMAGE_PIXELS_EXCEEDED",
                "image pixel count exceeds the preview limit",
            ) from exc
        except (OSError, UnidentifiedImageError) as exc:
            raise AppError(422, "PREVIEW_IMAGE_INVALID", "image cannot be opened") from exc

        try:
            if preview.width > config.max_render_width:
                preview.thumbnail(
                    (config.max_render_width, preview.height), Image.Resampling.LANCZOS
                )
            output = output_dir / "page-0001.webp"
            _write_webp(preview, output, config)
        finally:
            preview.close()
        page = _validate_webp(output, 1)
        if progress is not None:
            progress(1, 1)
        return PreviewRenderResult(pages=(page,), total_size_bytes=page.size_bytes)
