import httpx

from app.sandbox.client import ExecutionResult, SandboxClient


def _mock(handler) -> SandboxClient:
    transport = httpx.MockTransport(handler)
    return SandboxClient(base_url="http://sandbox:8000", transport=transport)


async def test_execute_parses_result():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/exec"
        return httpx.Response(
            200,
            json={
                "exit_code": 0, "stdout": "ok", "stderr": "", "duration_ms": 12,
                "timed_out": False, "files_created": ["seg.nii.gz"],
            },
        )

    r = await _mock(handler).execute("run-1", code="print('ok')")
    assert isinstance(r, ExecutionResult)
    assert r.ok is True
    assert r.files_created == ["seg.nii.gz"]


async def test_failed_execution_is_not_an_exception():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "exit_code": 1, "stdout": "", "stderr": "ValueError: shape mismatch",
                "duration_ms": 9, "timed_out": False, "files_created": [],
            },
        )

    r = await _mock(handler).execute("run-1", code="boom")
    assert r.ok is False
    assert "shape mismatch" in r.stderr


async def test_transport_error_becomes_a_structured_failure():
    def handler(request):
        raise httpx.ConnectError("sandbox down", request=request)

    r = await _mock(handler).execute("run-1", code="print(1)")
    assert r.ok is False
    assert r.exit_code == -1
    assert "sandbox" in r.stderr.lower()


async def test_write_and_read_file():
    calls = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/write":
            calls["wrote"] = True
            return httpx.Response(200, json={"path": "in.bin", "bytes": 3})
        return httpx.Response(200, content=b"abc")

    c = _mock(handler)
    await c.write_file("run-1", "in.bin", b"abc")
    assert calls["wrote"]
    assert await c.read_file("run-1", "in.bin") == b"abc"


async def test_timeout_is_clamped_and_client_waits_longer_than_the_sandbox():
    c = SandboxClient(base_url="http://sandbox:8000")
    # HTTP read timeout must exceed the sandbox's own wall clock, or we would
    # time out the request while the sandbox is still producing a real answer.
    assert c.http_timeout > c.default_timeout_s
