FROM dockerproxy.net/library/python:3.11.14-slim@sha256:c8271b1f627d0068857dce5b53e14a9558603b527e46f1f901722f935b786a39 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup --system --gid 1000 appuser \
    && adduser --system --uid 1000 --ingroup appuser --home /app --shell /usr/sbin/nologin appuser

COPY requirements.txt ./
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" -r requirements.txt

COPY app ./app
COPY scripts ./scripts
RUN mkdir -p /data/input /data/output /data/db /data/storage \
    && chown -R appuser:appuser /app /data

FROM base AS test
COPY requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY tests ./tests
ENV PYTHONPATH=/app
USER appuser
CMD ["python", "-m", "pytest", "-q"]

FROM base AS runtime

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
