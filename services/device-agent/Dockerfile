FROM python:3.13-slim-trixie AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/app
COPY requirements.txt ./
RUN python -m pip install --target /opt/app/site-packages -r requirements.txt
COPY *.py ./
RUN mkdir -p /opt/runtime-data

FROM gcr.io/distroless/python3-debian13:nonroot

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/site-packages

WORKDIR /app
COPY --from=builder --chown=nonroot:nonroot /opt/app /app
COPY --from=builder --chown=nonroot:nonroot /opt/runtime-data /var/lib/nexolab

USER nonroot
EXPOSE 8081
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD ["/usr/bin/python3", "-c", "import json,urllib.request; json.load(urllib.request.urlopen('http://127.0.0.1:8081/health', timeout=2))"]

CMD ["main.py"]
