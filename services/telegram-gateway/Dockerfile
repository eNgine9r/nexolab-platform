# Source-only candidate: patch upstream CVE-2026-19445 without Debian's
# vulnerable distroless/python3 interpreter or a larger full Python image.
FROM python:3.13.16-slim-trixie AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/app
COPY requirements.txt ./
RUN python -m pip install --target /opt/app/site-packages -r requirements.txt \
    && PYTHONPATH=/opt/app/site-packages python -m pip check
COPY app ./app

# Keep only application deps and fixed CPython, not build-time package tooling.
# SQLite is needed by the rootless delivery outbox and is absent from distroless/base.
RUN mkdir -p /opt/runtime-data /opt/runtime-libs \
    && find /opt/app -type d -exec chmod 0755 {} + \
    && find /opt/app -type f -exec chmod 0644 {} + \
    && sqlite_lib="$(find /usr/lib -name libsqlite3.so.0 -print -quit)" \
    && test -n "$sqlite_lib" \
    && cp -L "$sqlite_lib" /opt/runtime-libs/libsqlite3.so.0 \
    && chmod 0644 /opt/runtime-libs/libsqlite3.so.0 \
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
COPY --from=builder --chown=nonroot:nonroot /opt/runtime-libs /usr/local/lib
COPY --from=builder --chown=nonroot:nonroot /opt/app /app
COPY --from=builder --chown=nonroot:nonroot /opt/runtime-data /app/data/telegram-delivery

USER nonroot
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["/usr/local/bin/python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health/ready', timeout=3)"]
CMD ["/usr/local/bin/python3", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
