FROM python:3.13-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        fonts-dejavu-core \
        mosquitto \
        mosquitto-clients \
    && command -v mosquitto_ctrl >/dev/null \
    && apt-get purge --yes --allow-remove-essential perl-base \
    && apt-get autoremove --yes \
    && rm -rf /var/lib/apt/lists/* /usr/share/doc/* /usr/share/man/*

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY bin/nexolab-dynsec-admin /usr/local/bin/nexolab-dynsec-admin

RUN chmod 0755 /usr/local/bin/nexolab-dynsec-admin \
    && useradd --create-home --uid 10001 nexolab
USER nexolab

EXPOSE 8082

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8082"]
