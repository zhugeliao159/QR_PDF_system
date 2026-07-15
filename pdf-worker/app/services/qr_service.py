from __future__ import annotations

from io import BytesIO

import qrcode
from qrcode.constants import ERROR_CORRECT_Q


class QrService:
    def __init__(self, public_base_url: str) -> None:
        self.public_base_url = public_base_url.rstrip("/")

    def qr_url(self, qr_id: str) -> str:
        return f"{self.public_base_url}/r/{qr_id}"

    def qr_png_url(self, qr_id: str) -> str:
        return f"{self.public_base_url}/bindings/{qr_id}/qr.png"

    def fixed_url(self, qr_id: str, version_id: int) -> str:
        return f"{self.public_base_url}/r/{qr_id}/versions/{version_id}"

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
        return self.png_for_url(self.qr_url(qr_id))

    def fixed_png(self, qr_id: str, version_id: int) -> bytes:
        return self.png_for_url(self.fixed_url(qr_id, version_id))
