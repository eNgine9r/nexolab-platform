# Isolated fixed-Python candidate for CVE-2026-19445.
# Debian 13's distroless/python3 bundles affected CPython 3.13.5.
# Build upstream fixed CPython 3.13.16 and transplant ONLY /usr/local
# into the minimal Debian13 distroless base, preserving nonroot identity.
# PR-only — never deploy without evidence and an explicit operator cutover.
FROM python:3.13.16-slim-trixie AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/app
COPY requirements.txt ./
RUN python -m pip install --target /opt/app/site-packages -r requirements.txt
COPY *.py ./
# pip, vendored setuptools/urllib3/msgpack and installer tooling are
# build-only and must not enter the minimal runtime image.
RUN mkdir -p /opt/runtime-data \
    && find /opt/app -type d -exec chmod 0755 {} + \
    && find /opt/app -type f -exec chmod 0644 {} + \
    && rm -rf /usr/local/lib/python3.13/site-packages/pip \
              /usr/local/lib/python3.13/site-packages/pip-*.dist-info \
              /usr/local/lib/python3.13/site-packages/setuptools \
              /usr/local/lib/python3.13/site-packages/setuptools-*.dist-info \
              /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13

FROM gcr.io/distroless/base-debian13:nonroot

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/site-packages \
    LD_LIBRARY_PATH=/usr/local/lib

WORKDIR /app
COPY --from=builder --chown=nonroot:nonroot /usr/local /usr/local
COPY --from=builder --chown=nonroot:nonroot /opt/app /app
COPY --from=builder --chown=nonroot:nonroot /opt/runtime-data /var/lib/nexolab

USER nonroot
EXPOSE 8081
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD ["/usr/local/bin/python3", "-c", "import json,urllib.request; json.load(urllib.request.urlopen('http://127.0.0.1:8081/health', timeout=2))"]

CMD ["/usr/local/bin/python3", "/app/adaptive_main.py"]
