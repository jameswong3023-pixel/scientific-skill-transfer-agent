#!/usr/bin/env bash
# Verifies every infrastructure and security claim the README makes.
# Run from the repository root with the compose stack up:
#
#     docker compose up -d --build
#     bash scripts/verify_stack.sh
#
# Works from Git Bash on Windows, WSL, macOS and Linux.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1

# The API's host port is configurable because Hyper-V reserves scattered TCP
# ranges on Windows and 8000 is commonly inside one. Read it the same way
# compose does: .env first, then the environment, then the 8000 default.
if [ -z "${API_PORT:-}" ] && [ -f .env ]; then
  API_PORT="$(grep -E '^API_PORT=' .env | tail -1 | cut -d= -f2- | tr -d '\r')"
fi
API_PORT="${API_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
API="http://localhost:${API_PORT}"

pass=0
fail=0

check() {
  local label="$1"; shift
  if "$@" >/dev/null 2>&1; then
    echo "  PASS  $label"; pass=$((pass+1))
  else
    echo "  FAIL  $label"; fail=$((fail+1))
  fi
}

echo "== services =="
for svc in postgres redis minio api worker sandbox frontend; do
  check "$svc is running" bash -c \
    "docker compose ps --status running --format '{{.Service}}' | tr -d '\r' | grep -qx $svc"
done

echo
echo "== health (API on port ${API_PORT}) =="
check "api reports all dependencies healthy" bash -c \
  "curl -sf ${API}/api/health | grep -q '\"status\":\"ok\"'"
check "frontend responds" bash -c "curl -sf -o /dev/null localhost:${FRONTEND_PORT}"

echo
echo "== sandbox isolation =="
check "sandboxnet is an internal network" bash -c \
  "docker network inspect ssta_sandboxnet --format '{{.Internal}}' | tr -d '\r' | grep -qx true"
check "sandbox is attached ONLY to sandboxnet" bash -c \
  "test \"\$(docker inspect -f '{{len .NetworkSettings.Networks}}' \
     \$(docker compose ps -q sandbox) | tr -d '\r')\" = 1"
check "sandbox CANNOT reach 1.1.1.1" bash -c \
  "! docker compose exec -T sandbox python -c \"
import socket; socket.setdefaulttimeout(5); socket.create_connection(('1.1.1.1',53))\""
check "sandbox CANNOT reach 8.8.8.8" bash -c \
  "! docker compose exec -T sandbox python -c \"
import socket; socket.setdefaulttimeout(5); socket.create_connection(('8.8.8.8',53))\""
check "sandbox CANNOT resolve or reach openrouter.ai" bash -c \
  "! docker compose exec -T sandbox python -c \"
import socket; socket.setdefaulttimeout(5); socket.create_connection(('openrouter.ai',443))\""
check "sandbox has no OPENROUTER_API_KEY" bash -c \
  "! docker compose exec -T sandbox printenv OPENROUTER_API_KEY"
check "sandbox has no DATABASE_URL" bash -c \
  "! docker compose exec -T sandbox printenv DATABASE_URL"
check "sandbox has no S3_SECRET_KEY" bash -c \
  "! docker compose exec -T sandbox printenv S3_SECRET_KEY"
check "sandbox has no REDIS_URL" bash -c \
  "! docker compose exec -T sandbox printenv REDIS_URL"
check "sandbox runs as uid 1000, not root" bash -c \
  "docker compose exec -T sandbox id -u | tr -d '\r' | grep -qx 1000"
check "sandbox has the scientific stack pre-baked" bash -c \
  "docker compose exec -T sandbox python -c \
   'import numpy, scipy, skimage, nibabel, SimpleITK, cv2, tifffile, pydicom, matplotlib, pandas'"
check "sandbox rejects a write outside its run workspace" bash -c \
  "docker compose exec -T sandbox python -c \"
import base64, json, urllib.error, urllib.request
body = {'run_id': 'verify', 'path': '../../etc/escape.txt',
        'content_b64': base64.b64encode(b'x').decode()}
req = urllib.request.Request('http://localhost:8000/write', data=json.dumps(body).encode(),
                             headers={'Content-Type': 'application/json'})
try:
    urllib.request.urlopen(req, timeout=10)
except urllib.error.HTTPError as e:
    raise SystemExit(0 if e.code == 400 else 1)
raise SystemExit(1)\""

echo
echo "== api can reach the sandbox =="
check "api -> sandbox healthz" bash -c \
  "docker compose exec -T api python -c \"
import httpx; assert httpx.get('http://sandbox:8000/healthz', timeout=10).status_code == 200\""

echo
echo "== secrets do exist where they are needed =="
check "api HAS an OPENROUTER_API_KEY" bash -c \
  "docker compose exec -T api printenv OPENROUTER_API_KEY | grep -q ."
check "worker HAS an OPENROUTER_API_KEY" bash -c \
  "docker compose exec -T worker printenv OPENROUTER_API_KEY | grep -q ."

echo
echo "== database =="
check "all 16 domain tables exist" bash -c \
  "test \$(docker compose exec -T postgres psql -U ${POSTGRES_USER:-ssta} -d ${POSTGRES_DB:-ssta} -tAc \
   \"SELECT count(*) FROM pg_tables WHERE schemaname='public'\" | tr -d '\r') -ge 16"
# The four checkpoint* tables are created lazily by AsyncPostgresSaver.setup() on
# the first analysis run, so counting them on a freshly-migrated database would
# fail for a reason that is not a fault. Open the checkpointer instead: that both
# proves it connects (it is best-effort and yields None when it cannot) and
# provisions the tables, so the count below is then meaningful on a cold stack too.
check "langgraph checkpointer connects and provisions its tables" bash -c \
  "docker compose exec -T api python -c \"
import asyncio
from app.agents.checkpointing import analysis_checkpointer
async def main():
    async with analysis_checkpointer() as saver:
        assert saver is not None, 'checkpointer unavailable'
asyncio.run(main())\""
check "langgraph checkpoint tables exist" bash -c \
  "test \$(docker compose exec -T postgres psql -U ${POSTGRES_USER:-ssta} -d ${POSTGRES_DB:-ssta} -tAc \
   \"SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'checkpoint%'\" \
   | tr -d '\r') -ge 1"

echo
echo "-- $pass passed, $fail failed --"
[ "$fail" -eq 0 ]
