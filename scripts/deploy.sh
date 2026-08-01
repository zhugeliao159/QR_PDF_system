#!/bin/sh
set -eu

usage() {
  cat <<'EOF'
Usage: scripts/deploy.sh [options]

Options:
  --public-url URL        Public QR base URL (default: http://127.0.0.1:18081)
  --admin-username NAME   Initial admin username (default: admin)
  --bind-address IP       Admin host bind address (default: 127.0.0.1)
  --site-name TEXT        Site name shown in the UI
  --pip-index-url URL     Python package index used during Docker build
  --skip-build            Use an already-built local runtime image
  --resume-existing       Resume an interrupted initial deployment with an existing DB
  -h, --help              Show this help

This script initializes the application only. It does not configure DNS, Nginx,
TLS certificates, firewall rules, or domain registration/filing.
EOF
}

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PUBLIC_URL=${PUBLIC_URL:-http://127.0.0.1:18081}
ADMIN_USERNAME=${ADMIN_USERNAME:-admin}
BIND_ADDRESS=${PDF_WORKER_BIND_ADDRESS:-127.0.0.1}
SITE_NAME_VALUE=${SITE_NAME:-练习册二维码管理系统}
PIP_INDEX_VALUE=""
SKIP_BUILD=false
RESUME_EXISTING=false

while [ "$#" -gt 0 ]; do
  case "$1" in
    --public-url) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; PUBLIC_URL=$2; shift 2 ;;
    --admin-username) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; ADMIN_USERNAME=$2; shift 2 ;;
    --bind-address) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; BIND_ADDRESS=$2; shift 2 ;;
    --site-name) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; SITE_NAME_VALUE=$2; shift 2 ;;
    --pip-index-url) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; PIP_INDEX_VALUE=$2; shift 2 ;;
    --skip-build) SKIP_BUILD=true; shift ;;
    --resume-existing) RESUME_EXISTING=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

for command_name in docker python3; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "Missing required command: $command_name" >&2
    exit 1
  }
done
docker compose version >/dev/null 2>&1 || {
  echo "Docker Compose v2 is required (docker compose)." >&2
  exit 1
}

cd "$PROJECT_DIR"
if [ -f data/pdf-worker/db/app.db ] && [ "$RESUME_EXISTING" = false ]; then
  echo "An existing QRPDF database was found." >&2
  echo "This script is for initial deployment; use --resume-existing only for an interrupted first deployment." >&2
  echo "For upgrades, follow docs/DEPLOYMENT.md and create a verified backup first." >&2
  exit 1
fi

python3 scripts/configure_deployment.py .env \
  --template .env.example \
  --password-output .initial-admin-password \
  --public-url "$PUBLIC_URL" \
  --admin-username "$ADMIN_USERNAME" \
  --bind-address "$BIND_ADDRESS" \
  --site-name "$SITE_NAME_VALUE"

docker compose config --quiet

if [ "$SKIP_BUILD" = false ]; then
  if [ -n "$PIP_INDEX_VALUE" ]; then
    docker compose build --build-arg "PIP_INDEX_URL=$PIP_INDEX_VALUE" pdf-worker
  else
    docker compose build pdf-worker
  fi
else
  docker image inspect qr-exercise-prototype-pdf-worker:local >/dev/null 2>&1 || {
    echo "--skip-build was used but qr-exercise-prototype-pdf-worker:local is missing." >&2
    exit 1
  }
fi

mkdir -p data/pdf-worker/input data/pdf-worker/output data/pdf-worker/db data/pdf-worker/storage
docker run --rm --user 0 \
  -v "$PROJECT_DIR/data/pdf-worker:/data" \
  qr-exercise-prototype-pdf-worker:local \
  sh -c 'chown 1000:1000 /data /data/input /data/output /data/db /data/storage'

docker compose up -d --no-build pdf-worker preview-worker student-public

attempt=0
while [ "$attempt" -lt 45 ]; do
  if docker compose exec -T pdf-worker \
      python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()" \
      >/dev/null 2>&1 \
    && docker compose exec -T student-public \
      python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()" \
      >/dev/null 2>&1; then
    break
  fi
  attempt=$((attempt + 1))
  sleep 2
done

if [ "$attempt" -ge 45 ]; then
  echo "Services did not become healthy in time." >&2
  docker compose ps -a
  docker compose logs --tail=100 pdf-worker preview-worker student-public
  exit 1
fi

docker compose ps pdf-worker preview-worker student-public
echo "QRPDF application deployment completed."
if [ -f .initial-admin-password ]; then
  echo "Read .initial-admin-password locally, verify login, then securely delete it."
fi
echo "Next: configure DNS, Nginx, HTTPS, and firewall rules using docs/DEPLOYMENT.md."
