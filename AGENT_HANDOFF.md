# Maintainer handoff

This repository intentionally contains no real server address, domain, account,
email, local filesystem path, SSH-key path, password, token, or `.env` value.

Canonical maintenance references:

- `README.md` — purpose, architecture, environment, and file map;
- `docs/USER_GUIDE.md` — bilingual administrator user guide;
- `docs/DEPLOYMENT.md` — bilingual deployment, upgrade, backup, and rollback guide;
- `docs/stage_07_permanent_qr_upload.md` — permanent-QR upload design;
- `docs/stage_05d_backup_restore_guide.md` — backup and recovery details.

Current product/database state: permanent QR workflow with Schema 8 web-managed
credentials. Preserve `.env` and `data/`, back up before migrations, and never
run `docker compose down -v` on an installation containing business data.
