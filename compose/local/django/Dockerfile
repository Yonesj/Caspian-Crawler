# ------------------------------- Builder Stage ------------------------------
FROM python:3.14-slim-bookworm AS builder

ENV PATH="/root/.local/bin:${PATH}" \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential curl ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ADD https://astral.sh/uv/install.sh /install.sh
RUN chmod +x /install.sh \
    && /install.sh \
    && rm /install.sh

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --all-groups --no-install-project

# -------------------------------- Local Stage -------------------------------
FROM python:3.14-slim-bookworm AS local

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:${PATH}"

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y postgresql-client \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
COPY compose/local/django/entrypoint.sh /entrypoint
RUN chmod +x /entrypoint

COPY . .

EXPOSE 8000

ENTRYPOINT ["/entrypoint"]
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
