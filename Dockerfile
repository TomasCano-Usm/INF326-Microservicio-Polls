FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/TomasCano-Usm/INF326-Microservicio-Polls"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN python -c "import psycopg; import sqlalchemy.dialects.postgresql.psycopg"

RUN groupadd --gid 10001 polls \
    && useradd --uid 10001 --gid polls --create-home --home-dir /home/polls \
        --shell /usr/sbin/nologin polls

COPY --chown=10001:10001 app ./app
COPY --chown=10001:10001 alembic.ini ./alembic.ini
COPY --chown=10001:10001 migrations ./migrations

USER 10001:10001

EXPOSE 8004

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004"]
