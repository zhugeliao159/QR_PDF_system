from __future__ import annotations

import logging
import socket
import time

from app.config import Settings
from app.database import Database
from app.services.decoupled import AssetService
from app.services.decoupled import AnswerResourceService, AnswerRevisionService, QrResolverService
from app.services.binding_service import BindingService
from app.services.batch_import_service import BatchImportService
from app.services.external_url import ExternalUrlValidator
from app.services.preview_service import PreviewService
from app.services.qr_service import QrService
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
    asset_service = AssetService(database, storage)
    service = PreviewService(settings, database, storage, asset_service)
    resource_service = AnswerResourceService(database)
    external_url_validator = ExternalUrlValidator(settings)
    revision_service = AnswerRevisionService(
        database,
        asset_service,
        external_url_validator,
        settings.require_preview_before_publish,
        service,
    )
    binding_service = BindingService(
        settings,
        database,
        storage,
        QrService(settings.public_base_url),
        resource_service,
        revision_service,
        asset_service,
        QrResolverService(database),
        external_url_validator,
        service,
    )
    batch_service = BatchImportService(
        settings, database, storage, binding_service, service
    )
    worker_id = f"preview-worker:{socket.gethostname()}"
    logger.info("preview worker started: %s", worker_id)
    while True:
        try:
            worked = batch_service.finalize_next()
            worked = batch_service.process_next(worker_id) or worked
            worked = service.process_next(worker_id) or worked
            if not worked:
                time.sleep(settings.preview_worker_poll_seconds)
        except Exception:
            logger.exception("preview worker loop failed")
            time.sleep(settings.preview_worker_poll_seconds)


if __name__ == "__main__":
    main()
