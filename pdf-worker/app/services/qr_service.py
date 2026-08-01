from __future__ import annotations

from io import BytesIO
import os
import tempfile
from pathlib import Path

import qrcode
from qrcode.constants import ERROR_CORRECT_Q


class QrService:
    def __init__(self, public_base_url: str, qr_codes_dir: Path | None = None) -> None:
        self.public_base_url = public_base_url.rstrip("/")
        self.qr_codes_dir = qr_codes_dir.resolve() if qr_codes_dir else None
        if self.qr_codes_dir is not None:
            self.qr_codes_dir.mkdir(parents=True, exist_ok=True)

    def qr_url(self, qr_id: str) -> str:
        return f"{self.public_base_url}/q/{qr_id}"

    def legacy_url(self, qr_id: str) -> str:
        return f"{self.public_base_url}/r/{qr_id}"

    def qr_png_url(self, qr_id: str) -> str:
        return f"{self.public_base_url}/bindings/{qr_id}/qr.png"

    def fixed_url(self, public_token: str) -> str:
        return self.qr_url(public_token)

    def fixed_qr_png_url(self, qr_id: str, version_id: int) -> str:
        return (
            f"{self.public_base_url}/bindings/{qr_id}/versions/{version_id}/qr.png"
        )

    @staticmethod
    def png_for_url(url: str) -> bytes:
        qr = qrcode.QRCode(
            version=None,
            error_correction=ERROR_CORRECT_Q,
            box_size=10,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)
        image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()

    def png(self, qr_id: str) -> bytes:
        if self.qr_codes_dir is None:
            return self.png_for_url(self.qr_url(qr_id))
        if not qr_id or any(
            not (character.isalnum() or character in {"-", "_"})
            for character in qr_id
        ):
            raise ValueError("invalid QR token")
        path = self.qr_codes_dir / f"{qr_id}.png"
        if path.is_file():
            return path.read_bytes()
        content = self.png_for_url(self.qr_url(qr_id))
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=".qr-", dir=self.qr_codes_dir, delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.replace(temporary, path)
            except OSError:
                if not path.is_file():
                    raise
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return path.read_bytes()

    def fixed_png(self, public_token: str) -> bytes:
        return self.png(public_token)
