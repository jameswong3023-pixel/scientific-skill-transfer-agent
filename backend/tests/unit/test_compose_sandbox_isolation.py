"""Assert the sandbox service's isolation posture by parsing the compose file.

This is the security boundary the whole project rests on: agent-generated code
runs in `sandbox`, so that container must have no route to the internet, no
credentials, and no published host port. Encoding those as tests means a
careless compose edit later breaks the build instead of quietly breaking the
guarantee.
"""

from pathlib import Path

import yaml

COMPOSE = Path(__file__).resolve().parents[3] / "docker-compose.yml"


def _compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_sandbox_service_exists():
    assert "sandbox" in _compose()["services"]


def test_sandbox_is_attached_only_to_the_internal_network():
    nets = _compose()["services"]["sandbox"]["networks"]
    assert nets == ["sandboxnet"], f"sandbox must be isolated, got {nets}"


def test_sandboxnet_is_internal():
    assert _compose()["networks"]["sandboxnet"]["internal"] is True


def test_sandbox_receives_no_secrets():
    env = _compose()["services"]["sandbox"].get("environment", {}) or {}
    keys = set(env.keys()) if isinstance(env, dict) else {e.split("=")[0] for e in env}
    forbidden = {"OPENROUTER_API_KEY", "DATABASE_URL", "S3_SECRET_KEY", "S3_ACCESS_KEY"}
    assert not (keys & forbidden), f"secrets leaked into sandbox: {keys & forbidden}"


def test_sandbox_publishes_no_host_ports():
    assert "ports" not in _compose()["services"]["sandbox"]


def test_sandbox_runs_unprivileged():
    svc = _compose()["services"]["sandbox"]
    assert svc.get("privileged") is not True
    assert svc.get("user") == "1000:1000"
