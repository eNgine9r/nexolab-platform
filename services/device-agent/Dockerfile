# CVE-2026-19445: Debian 13's distroless/python3 runtime still ships
# python3.13 3.13.5-2+deb13u5. Use upstream fixed CPython >=3.13.16
# while investigating a restored distroless/nonroot production runtime.
# This is PR-only / NOT deployed to the live Raspberry Pi.
FROM python:3.13.16-slim-trixie AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/app
COPY requirements.txt ./
RUN python -m pip install --target /opt/app/site-packages -r requirements.txt
COPY *.py ./
RUN mkdir -p /opt/runtime-data \
    && find /opt/app -type d -exec chmod 0755 {} + \
    && find /opt/app -type f -exec chmod 0644 {} +

# Temporary source-scoped release candidate, not a security exception.
# Nonroot identity is retained; no runtime apt/pip install or shell invocation.
FROM python:3.13.16-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/site-packages

WORKDIR /app
COPY --from=builder --chown=65532:65532 /opt/app /app
COPY --from=builder --chown=65532:65532 /opt/runtime-data /var/lib/nexolab

USER 65532:65532
EXPOSE 8081
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import json,urllib.request; json.load(urllib.request.urlopen('http://127.0.0.1:8081/health', timeout=2))"]

CMD ["python", "/app/adaptive_main.py"]
