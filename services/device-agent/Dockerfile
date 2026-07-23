FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --create-home --uid 10001 nexolab \
    && mkdir -p /var/lib/nexolab \
    && chown -R nexolab:nexolab /var/lib/nexolab

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./

USER nexolab
EXPOSE 8081
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import json,urllib.request; json.load(urllib.request.urlopen('http://127.0.0.1:8081/health', timeout=2))"

CMD ["python", "main.py"]
