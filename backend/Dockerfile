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
#
# The migrations run HERE, so a migration ships with its code and cannot be
# forgotten. Until 2026-09-11 this line started uvicorn alone, the host was
# believed to migrate, and nothing did: 0018–0021 never reached production and
# `GET /favorites` answered 500 right after sign-in. Not a host setting either —
# Railway's Config as Code is closed to services that never used it, and a
# dashboard field lives outside the repository.
#
# An anti-pattern beyond one replica (two containers starting together run two
# migrations), the right trade-off at one: docs/DEPLOY.md §6 quater.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host ${BIND_HOST:-0.0.0.0} --port ${PORT:-8000}"]
