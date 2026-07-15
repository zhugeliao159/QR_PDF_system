from __future__ import annotations

import logging
import socket
import time

from app.config import Settings
from app.database import Database
from app.services.decoupled import AssetService
from app.services.preview_service import PreviewService
from app.storage.local import LocalStorageBackend


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    settings = Settings.from_env()
    settings.ensure_directories()
    database = Database(settings.database_path)
    database.initialize()
    storage = LocalStorageBackend(settings)
    storage.ensure_directories()
    service = PreviewService(settings, database, storage, AssetService(database, storage))
    worker_id = f"preview-worker:{socket.gethostname()}"
    logger.info("preview worker started: %s", worker_id)
    while True:
        try:
            if not service.process_next(worker_id):
                time.sleep(settings.preview_worker_poll_seconds)
        except Exception:
            logger.exception("preview worker loop failed")
            time.sleep(settings.preview_worker_poll_seconds)


if __name__ == "__main__":
    main()
