FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=8

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

# Install dependencies first so this layer caches across source edits. At this
# point `app/` does not exist yet, so setuptools' packages.find matches nothing
# and the `app` package itself is NOT registered by this step.
COPY pyproject.toml ./
# The pip cache is mounted rather than disabled. This image pulls scipy, numpy
# and pymupdf -- tens of megabytes -- and on an unreliable link a partial
# download otherwise fails the whole layer and the next attempt starts from
# zero. With the cache mount a retry resumes from what already arrived. The
# cache lives in the builder, not in the final image, so nothing is shipped.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip setuptools wheel && pip install -e ".[dev]"

COPY . .

# Now that the source is present, re-run the editable install to actually
# register the `app` package. Without this the container only imports `app`
# by accident, because uvicorn and pytest happen to put the working directory
# on sys.path -- which breaks the moment anything runs from another directory.
#
# --no-build-isolation is what keeps this step offline: PEP 517 would otherwise
# download a fresh copy of setuptools/wheel into a throwaway build env, even
# though both are already installed above. That download is pure risk on a
# flaky link and buys nothing.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -e ".[dev]" --no-deps --no-build-isolation

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /srv
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
