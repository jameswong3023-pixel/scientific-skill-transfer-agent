.PHONY: up down logs build test test-integration fmt migrate seed reset verify

up:                ; docker compose up -d --build
down:              ; docker compose down
reset:             ; docker compose down -v
logs:              ; docker compose logs -f api worker
build:             ; docker compose build
migrate:           ; docker compose run --rm api alembic upgrade head
seed:              ; docker compose run --rm api python -m scripts.seed_demo
test:              ; cd backend && python -m pytest tests/unit -v
test-integration:  ; docker compose run --rm api python -m pytest tests/integration -v
fmt:               ; cd backend && ruff check --fix . && ruff format .
verify:            ; bash scripts/verify_stack.sh
