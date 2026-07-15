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

    def png(self, qr_id: str) -> bytes:
        qr = qrcode.QRCode(
            version=None,
            error_correction=ERROR_CORRECT_Q,
            box_size=10,
            border=4,
        )
        qr.add_data(self.qr_url(qr_id))
        qr.make(fit=True)
        image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
