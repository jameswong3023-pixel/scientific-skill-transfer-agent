.PHONY: up down logs build venv test lint test-integration test-e2e fmt migrate seed demo phantom reset verify

# Resolve the backend virtualenv's interpreter across POSIX and Windows layouts,
# falling back to whatever `python` is on PATH. A bare host python usually does
# not have numpy/nibabel/fastapi, so `make test` against it fails at collection.
define PY
if [ -x .venv/bin/python ]; then P=.venv/bin/python; \
elif [ -x .venv/Scripts/python.exe ]; then P=.venv/Scripts/python.exe; \
else P=python; fi
endef

up:                ; docker compose up -d --build
down:              ; docker compose down
reset:             ; docker compose down -v
logs:              ; docker compose logs -f api worker
build:             ; docker compose build
migrate:           ; docker compose run --rm api alembic upgrade head

# The `seed` compose service (profile "tools") reuses the backend image, which
# already has httpx/numpy/scipy/nibabel, and bind-mounts the repo so the phantom
# it generates lands back on the host. That keeps Docker the only prerequisite.
seed:              ; docker compose run --rm seed
demo:              ; docker compose run --rm seed --wait
phantom:           ; docker compose run --rm --entrypoint python seed scripts/make_phantom.py --out fixtures/phantom

# One-time setup for the host test path.
venv:
	cd backend && python -m venv .venv && \
	  ( .venv/bin/pip install -e ".[dev]" || .venv/Scripts/pip install -e ".[dev]" )

test:
	@cd backend && $(PY) && $$P -m pytest tests/unit -q

lint:
	@cd backend && $(PY) && $$P -m ruff check . ../scripts

fmt:
	@cd backend && $(PY) && $$P -m ruff check --fix . && $$P -m ruff format .

test-e2e:
	@cd backend && $(PY) && RUN_E2E=1 $$P -m pytest tests/integration/test_full_experiment.py -v -s

# Runs inside the api container: the resilience suite reaches the sandbox, and
# sandboxnet is internal so it is not reachable from the host.
test-integration:  ; docker compose exec -T -e RUN_INTEGRATION=1 api python -m pytest tests/integration -v

verify:            ; bash scripts/verify_stack.sh
