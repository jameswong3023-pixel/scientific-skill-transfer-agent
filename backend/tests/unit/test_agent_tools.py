from app.agents.tools.sandbox_tools import (
    TOOL_NAMES,
    TOOL_SCHEMAS,
    ToolContext,
    dispatch_tool,
)
from app.sandbox.client import ExecutionResult


class FakeSandbox:
    def __init__(self, result=None, files=None):
        self.result = result or ExecutionResult(exit_code=0, stdout="done", duration_ms=5)
        self.files = files if files is not None else [{"path": "data/t1.nii.gz", "bytes": 100}]
        self.written = {}
        self.executed = []

    async def execute(self, run_id, code=None, filename="script.py", argv=None, timeout_s=None):
        self.executed.append({"filename": filename, "code": code})
        return self.result

    async def list_files(self, run_id):
        return self.files

    async def read_file(self, run_id, path):
        return b"file contents here"

    async def write_file(self, run_id, path, data):
        self.written[path] = data

    async def packages(self):
        return [{"name": "numpy", "version": "2.2.1"}]


async def _noop_emit(node, title, payload=None, kind="node", detail=""):
    return None


def _ctx(sandbox=None) -> ToolContext:
    return ToolContext(run_id="r1", sandbox=sandbox or FakeSandbox(), emit=_noop_emit)


def test_exactly_seven_tools_are_exposed():
    assert len(TOOL_SCHEMAS) == 7
    assert TOOL_NAMES == {
        "list_files", "inspect_image", "read_text",
        "write_file", "run_python", "list_packages", "save_artifact",
    }


def test_every_schema_is_wellformed():
    for schema in TOOL_SCHEMAS:
        fn = schema["function"]
        assert schema["type"] == "function"
        assert fn["name"] in TOOL_NAMES
        assert fn["description"]
        assert fn["parameters"]["type"] == "object"


def test_no_tool_reveals_ground_truth():
    blob = str(TOOL_SCHEMAS).lower()
    assert "ground_truth" not in blob
    assert "ground truth" not in blob


async def test_list_files_returns_paths():
    out = await dispatch_tool(_ctx(), "list_files", {})
    assert "data/t1.nii.gz" in out


async def test_run_python_returns_success_observation():
    sandbox = FakeSandbox()
    out = await dispatch_tool(_ctx(sandbox), "run_python", {"code": "print(1)", "filename": "a.py"})
    assert "Exit 0" in out
    assert sandbox.executed[0]["filename"] == "a.py"


async def test_run_python_surfaces_failure_for_the_agent_to_repair():
    sandbox = FakeSandbox(
        ExecutionResult(exit_code=1, stderr="ValueError: shape mismatch", duration_ms=7)
    )
    out = await dispatch_tool(_ctx(sandbox), "run_python", {"code": "boom"})
    assert "FAILED" in out
    assert "shape mismatch" in out


async def test_write_file_persists():
    sandbox = FakeSandbox()
    await dispatch_tool(_ctx(sandbox), "write_file", {"path": "seg.py", "content": "x=1"})
    assert sandbox.written["seg.py"] == b"x=1"


async def test_save_artifact_records_it():
    ctx = _ctx()
    await dispatch_tool(ctx, "save_artifact", {"path": "outputs/seg.nii.gz", "kind": "output",
                                               "description": "segmentation"})
    assert ctx.artifacts[0]["path"] == "outputs/seg.nii.gz"
    assert ctx.artifacts[0]["kind"] == "output"


async def test_list_packages_tells_the_agent_what_it_has():
    out = await dispatch_tool(_ctx(), "list_packages", {})
    assert "numpy" in out


async def test_unknown_tool_returns_guidance_not_an_exception():
    out = await dispatch_tool(_ctx(), "pip_install", {"package": "torch"})
    assert "unknown tool" in out.lower()
    assert "list_files" in out, "must tell the model what it CAN call"


async def test_tool_exception_becomes_an_observation():
    class Broken(FakeSandbox):
        async def list_files(self, run_id):
            raise RuntimeError("sandbox exploded")

    out = await dispatch_tool(_ctx(Broken()), "list_files", {})
    assert "error" in out.lower()
    assert "sandbox exploded" in out


async def test_inspect_image_reports_shape_and_dtype(tmp_path):
    import nibabel as nib
    import numpy as np

    arr = np.zeros((4, 5, 6), dtype=np.float32)
    p = tmp_path / "v.nii.gz"
    nib.save(nib.Nifti1Image(arr, np.eye(4)), str(p))

    class VolSandbox(FakeSandbox):
        async def read_file(self, run_id, path):
            return p.read_bytes()

    out = await dispatch_tool(_ctx(VolSandbox()), "inspect_image", {"path": "data/v.nii.gz"})
    assert "[4, 5, 6]" in out or "4, 5, 6" in out
