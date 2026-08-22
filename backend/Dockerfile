FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

RUN pip install --no-cache-dir poetry==2.1.3

# The lock file is copied too: without it the container and the CI resolve
# their own versions, and "it works in Docker" stops meaning anything.
COPY pyproject.toml poetry.lock ./
RUN poetry install --no-root --no-interaction

COPY . .

EXPOSE 8000

# Shell form so the deployment can set the two, and only the two, that differ
# between a laptop and a host (I8).
#
# BIND_HOST MUST BE `::` ON A HOST WHOSE PRIVATE NETWORK IS IPv6-ONLY —
# Railway is one. `0.0.0.0` binds IPv4 only, so the container starts, looks
# healthy, and is unreachable from every other service: a failure that reads as
# "the proxy is misconfigured" and is not. `::` accepts both families.
CMD ["sh", "-c", "uvicorn app.main:app --host ${BIND_HOST:-0.0.0.0} --port ${PORT:-8000}"]
