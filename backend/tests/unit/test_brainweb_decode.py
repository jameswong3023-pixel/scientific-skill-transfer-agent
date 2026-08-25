import sys
from pathlib import Path

import numpy as np
import pytest

# scripts/ is repository tooling, not part of the shipped backend image, so the
# module is not importable when this suite is run inside the api container.
SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if not (SCRIPTS / "fetch_brainweb.py").exists():  # pragma: no cover - container path
    pytest.skip("scripts/ is not present (running inside the app image)", allow_module_level=True)

sys.path.insert(0, str(SCRIPTS))

from fetch_brainweb import (  # noqa: E402
    PHANTOM_LABEL_MAP,
    build_request,
    collapse_labels,
    rawb_to_array,
)


def test_decodes_raw_bytes_into_the_expected_volume_shape():
    payload = bytes(np.arange(2 * 3 * 4, dtype=np.uint8))
    arr = rawb_to_array(payload, shape=(2, 3, 4))
    assert arr.shape == (2, 3, 4)
    assert arr.dtype == np.uint8


def test_wrong_payload_size_raises_clearly():
    with pytest.raises(ValueError, match="expected"):
        rawb_to_array(b"\x00" * 10, shape=(181, 217, 181))


def test_request_carries_the_documented_fields():
    body = build_request("t1", noise=3, rf=20)
    assert body["download_for_real"] == "[Start download!]"
    assert body["format_value"] == "raw_byte"
    assert "3" in body["noise_value"]
    assert "20" in body["rf_value"]


def test_phantom_request_asks_for_the_discrete_label_volume():
    body = build_request("phantom", noise=0, rf=0)
    assert "phantom" in str(body).lower() or "crisp" in str(body).lower()


def test_label_collapse_keeps_the_four_scored_classes_and_drops_the_rest():
    """BrainWeb ships 11 tissue classes; the phantom and the evaluator both use
    four. Anything else must map to background or the Hungarian label matcher
    is comparing against classes that do not exist on our side."""
    source = np.array([[[0, 1, 2, 3, 4, 5, 8, 10]]], dtype=np.uint8)
    collapsed = collapse_labels(source)
    assert collapsed.tolist() == [[[0, 1, 2, 3, 0, 0, 0, 0]]]
    assert set(PHANTOM_LABEL_MAP.values()) == {0, 1, 2, 3}


def test_collapse_leaves_the_input_untouched():
    source = np.full((2, 2, 2), 4, dtype=np.uint8)
    collapse_labels(source)
    assert source.max() == 4, "collapse_labels must not mutate its argument"
