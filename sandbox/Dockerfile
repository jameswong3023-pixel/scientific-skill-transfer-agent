FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MPLBACKEND=Agg \
    HOME=/tmp

RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 libgl1 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY executor ./executor

# Agent code runs as this unprivileged user, never root.
RUN useradd -m -u 1000 sandboxer && mkdir -p /work && chown -R sandboxer:sandboxer /work /srv

USER 1000:1000
EXPOSE 8000
CMD ["uvicorn", "executor.server:app", "--host", "0.0.0.0", "--port", "8000"]
