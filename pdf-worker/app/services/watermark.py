from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.config import Settings


class WatermarkService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.font_path = Path(settings.watermark_font_path) if settings.watermark_font_path else None
        self.configured_font_available = bool(self.font_path and self.font_path.is_file())
        self.chinese_watermark_available = False
        self._font = self._load_font()

    def _load_font(self):
        if self.configured_font_available:
            try:
                font = ImageFont.truetype(str(self.font_path), self.settings.watermark_font_size)
                masks = [bytes(font.getmask(char)) for char in ("在", "线", "预", "览")]
                self.chinese_watermark_available = len(set(masks)) > 1
                return font
            except OSError:
                self.configured_font_available = False
        return ImageFont.load_default()

    def text(self, material_code: str, trace_code: str, now: datetime | None = None) -> str:
        timestamp = (now or datetime.now(timezone.utc)).astimezone().strftime("%Y-%m-%d %H:%M")
        if not self.chinese_watermark_available:
            return f"PREVIEW ONLY | {trace_code} | {material_code} | {timestamp}"
        try:
            return self.settings.watermark_text_template.format(
                material_code=material_code,
                trace_code=trace_code,
                timestamp=timestamp,
            )
        except (KeyError, ValueError):
            return f"在线预览 | {material_code} | {trace_code} | {timestamp}"

    def render(self, source_path: Path, material_code: str, trace_code: str) -> bytes:
        with Image.open(source_path) as source:
            base = source.convert("RGB")
        label = self.text(material_code, trace_code)
        probe = ImageDraw.Draw(base)
        bounds = probe.textbbox((0, 0), label, font=self._font)
        text_width = max(1, bounds[2] - bounds[0])
        text_height = max(1, bounds[3] - bounds[1])
        pad = max(8, self.settings.watermark_font_size // 2)
        tile = Image.new("RGBA", (text_width + pad * 2, text_height + pad * 2), (0, 0, 0, 0))
        draw = ImageDraw.Draw(tile)
        draw.text(
            (pad - bounds[0], pad - bounds[1]), label, font=self._font,
            fill=(70, 70, 70, self.settings.watermark_opacity),
        )
        rotated = tile.rotate(
            self.settings.watermark_rotation_degrees, expand=True, resample=Image.Resampling.BICUBIC
        )
        base.paste(
            rotated,
            ((base.width - rotated.width) // 2, (base.height - rotated.height) // 2),
            rotated,
        )
        for y in range(-rotated.height, base.height + rotated.height, self.settings.watermark_spacing_y):
            row = (y // self.settings.watermark_spacing_y) & 1
            offset = -(self.settings.watermark_spacing_x // 2) if row else 0
            for x in range(-rotated.width + offset, base.width + rotated.width, self.settings.watermark_spacing_x):
                base.paste(rotated, (x, y), rotated)
        output = BytesIO()
        base.save(output, format="WEBP", quality=82, method=4)
        base.close()
        tile.close()
        rotated.close()
        return output.getvalue()
