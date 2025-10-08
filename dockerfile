# syntax=docker/dockerfile:1.6
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    ZK_TOOLS_SECRET=change-me

WORKDIR /app

# Instala dependencias del sistema (para openpyxl/pyzk puede requerir tzdata y build tools)
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential git tzdata iputils-ping && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . /app

EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "app:app"]
