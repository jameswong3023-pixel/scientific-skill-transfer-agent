"""Pins a known, currently-unfixed defect so it cannot be forgotten.

`frontend/hooks/useSliceCount.ts` learns a volume's depth by reading the
`X-Slice-Count` response header, and it asks for it with:

    fetch(url, { method: "HEAD" })

FastAPI 0.115 registers every `@router.get(...)` route with `methods={"GET"}` and
does **not** synthesise a HEAD handler the way bare Starlette's `Route` does. So
that probe gets HTTP 405, the hook's `.catch()` swallows it, and the slice count
silently falls back to 1 — the axis tabs and the opacity slider still work, but
the scrubber has nothing to scrub. Verified against the running stack: HEAD on
`/api/artifacts/{id}/slice` returns 405 both directly and through the Next.js
rewrite, while GET on the same URL returns a correct PNG with
`X-Slice-Count: 64`.

The test is `xfail(strict=True)` rather than an assertion of the broken
behaviour: it fails the build the moment someone fixes the mismatch, which is the
prompt to delete this file and replace it with a real assertion. Fixing it is one
line on either side of the boundary — `method: "GET"` in the hook, or
`methods=["GET", "HEAD"]` on the two slice routes — but it touches `frontend/`
and `backend/app/`, both of which were explicitly out of scope for the change
that found it.
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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "KNOWN DEFECT: the frontend probes these routes with HEAD to read "
        "X-Slice-Count, but FastAPI registers them GET-only, so the probe 405s "
        "and slice navigation silently collapses to a single slice."
    ),
)
@pytest.mark.parametrize("path", SLICE_ROUTES)
def test_slice_routes_answer_the_head_probe_the_frontend_sends(path):
    assert "HEAD" in _methods_for(path)
