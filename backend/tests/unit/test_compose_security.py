"""Assert the compose file's security posture as a parseable property.

`docker network inspect ssta_sandboxnet --format '{{.Internal}}'` proves this at
runtime, but that needs a running daemon. Parsing the compose file makes the
same guarantees testable in CI and catches a regression at edit time rather than
at deploy time.
"""

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

COMPOSE = Path(__file__).resolve().parents[3] / "docker-compose.yml"


def _compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_compose_file_exists():
    assert COMPOSE.is_file(), f"missing compose file at {COMPOSE}"


def test_sandbox_network_has_no_route_to_the_internet():
    networks = _compose()["networks"]
    assert "sandboxnet" in networks, "sandboxnet must be declared"
    assert networks["sandboxnet"].get("internal") is True, (
        "sandboxnet must be internal: true -- this is what makes 'agent code "
        "cannot phone home' a verifiable property rather than a promise"
    )


def test_no_service_publishes_the_sandbox_network_to_the_host():
    """Any service on sandboxnet that also publishes ports would bridge it."""
    compose = _compose()
    for name, svc in compose["services"].items():
        nets = svc.get("networks") or []
        if "sandboxnet" not in nets:
            continue
        # api legitimately publishes 8000 and sits on edge; it is the trusted
        # broker. Nothing else on sandboxnet may expose a host port.
        if name == "api":
            continue
        assert not svc.get("ports"), (
            f"service {name!r} is on sandboxnet and publishes host ports {svc['ports']}"
        )


def test_postgres_and_redis_are_not_reachable_from_the_host():
    """Data stores stay on the internal core network with no port mapping."""
    services = _compose()["services"]
    for name in ("postgres", "redis"):
        assert not services[name].get("ports"), (
            f"{name} must not publish a host port; it is reached over the core network"
        )


def test_every_service_declares_its_networks_explicitly():
    for name, svc in _compose()["services"].items():
        assert svc.get("networks"), f"service {name!r} must declare its networks explicitly"
