"""The slice routes must answer the HEAD probe the viewer sends.

`frontend/hooks/useSliceCount.ts` learns a volume's depth by reading the
`X-Slice-Count` response header, and asks for it with:

    fetch(url, { method: "HEAD" })

FastAPI registers every `@router.get(...)` route with `methods={"GET"}` and does
not synthesise a HEAD handler the way bare Starlette's `Route` does. When these
routes were GET-only that probe returned 405, the hook's `.catch()` swallowed
it, and the slice count silently fell back to 1 — the axis tabs and opacity
slider still worked, so the failure looked like a volume that happened to have
one slice rather than a broken request. Verified against the running stack at
the time: HEAD returned 405 both directly and through the Next.js rewrite,
while GET on the same URL returned a correct PNG with `X-Slice-Count: 64`.

The routes now declare HEAD explicitly. HEAD is the right verb here — the probe
wants a header, not a PNG — and Starlette drops the body, so it stays cheap.
"""

import pytest

from app.main import app

SLICE_ROUTES = (
    "/api/artifacts/{artifact_id}/slice",
    "/api/datasets/files/{file_id}/slice",
)


def _methods_for(path: str) -> set[str]:
    for route in app.routes:
        if getattr(route, "path", None) == path:
            return set(getattr(route, "methods", ()) or ())
    raise AssertionError(f"route not registered: {path}")


def test_the_slice_routes_exist_and_serve_get():
    for path in SLICE_ROUTES:
        assert "GET" in _methods_for(path)


@pytest.mark.parametrize("path", SLICE_ROUTES)
def test_slice_routes_answer_the_head_probe_the_frontend_sends(path):
    assert "HEAD" in _methods_for(path), (
        f"{path} does not accept HEAD; the viewer's X-Slice-Count probe will 405 "
        "and slice navigation will silently collapse to a single slice"
    )
