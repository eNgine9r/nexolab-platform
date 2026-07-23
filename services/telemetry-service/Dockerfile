FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app

RUN useradd --create-home --uid 10001 nexolab
USER nexolab

EXPOSE 8082

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8082"]
