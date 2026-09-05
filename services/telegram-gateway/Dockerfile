FROM python:3.13-slim-trixie AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/app
COPY requirements.txt ./
RUN python -m pip install --target /opt/app/site-packages -r requirements.txt \
    && PYTHONPATH=/opt/app/site-packages python -m pip check
COPY app ./app
RUN mkdir -p /opt/runtime-data \
    && find /opt/app -type d -exec chmod 0755 {} + \
    && find /opt/app -type f -exec chmod 0644 {} +

FROM gcr.io/distroless/python3-debian13:nonroot

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/site-packages

WORKDIR /app
COPY --from=builder --chown=nonroot:nonroot /opt/app /app
COPY --from=builder --chown=nonroot:nonroot /opt/runtime-data /app/data/telegram-delivery

USER nonroot
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["/usr/bin/python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health/ready', timeout=3)"]
CMD ["-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
