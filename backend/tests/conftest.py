"""Test-wide environment guards.

pytest imports conftest before any test module, which is the only window in
which these take effect: `app.config` builds its Settings singleton at import
time, and `app.storage.s3` builds its boto3 client from that singleton.
"""

import os

# Unit tests must never touch the network. The default endpoint is the
# compose-internal hostname `minio`, which does not resolve outside the stack --
# and a failed DNS lookup is not covered by botocore's connect_timeout, so a
# stray call hangs on the OS resolver for minutes. Port 9 (discard) on loopback
# refuses instantly instead, turning any accidental storage call into a fast,
# obvious failure.
os.environ.setdefault("S3_ENDPOINT_URL", "http://127.0.0.1:9")

# Unit tests exercise the app through TestClient, which runs the lifespan hook.
# The startup bucket check has nothing to talk to here, and botocore's retry
# backoff would add ~12s per TestClient instantiation.
os.environ.setdefault("S3_ENSURE_BUCKET_ON_STARTUP", "false")

# Same reasoning for Postgres and Redis: keep failures immediate and local.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ssta:ssta@127.0.0.1:9/ssta")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:9/0")
