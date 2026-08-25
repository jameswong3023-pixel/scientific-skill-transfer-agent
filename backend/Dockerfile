FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

# Install dependencies first so this layer caches across source edits. At this
# point `app/` does not exist yet, so setuptools' packages.find matches nothing
# and the `app` package itself is NOT registered by this step.
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install -e ".[dev]"

COPY . .

# Now that the source is present, re-run the editable install to actually
# register the `app` package. Without this the container only imports `app`
# by accident, because uvicorn and pytest happen to put the working directory
# on sys.path -- which breaks the moment anything runs from another directory.
RUN pip install -e ".[dev]" --no-deps

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /srv
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
