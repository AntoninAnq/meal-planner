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

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
