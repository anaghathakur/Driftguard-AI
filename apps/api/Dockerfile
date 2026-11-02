FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

WORKDIR /app

RUN addgroup --system driftguard && adduser --system --ingroup driftguard driftguard

COPY apps/api/pyproject.toml ./apps/api/pyproject.toml
COPY apps/api/app ./apps/api/app
COPY apps/api/models ./apps/api/models

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ./apps/api

RUN chown -R driftguard:driftguard /app

USER driftguard

EXPOSE 8080

CMD ["sh", "-c", "uvicorn apps.api.app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers"]
