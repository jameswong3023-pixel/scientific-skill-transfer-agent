"""The Skill representation.

Design intent: the schema is optimised for a *downstream coding agent*, not for
human reading. Every field answers "what do I have to do", and every claim is
either tied to a verbatim quote + page, or explicitly flagged `inferred: true`.
That flag is what lets the UI answer the brief's question "which parts did you
infer rather than extract?".
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Provenance(BaseModel):
    quote: str = Field(description="Verbatim sentence or clause from the paper")
    page: int = Field(description="1-based page number the quote appears on")


class Parameter(BaseModel):
    symbol: str = ""
    name: str = ""
    value: str = ""
    units: str = ""
    role: str = ""
    inferred: bool = False
    provenance: Provenance | None = None


class AlgorithmStep(BaseModel):
    order: int
    operation: str
    equation: str | None = None
    notes: str | None = None
    inferred: bool = False
    provenance: Provenance | None = None


class ValidationCheck(BaseModel):
    name: str
    description: str = ""
    expected: str = ""


class Skill(BaseModel):
    name: str
    description: str
    intended_task: str
    modality: str = "unknown"

    input_requirements: list[str] = Field(default_factory=list)
    output_specification: list[str] = Field(default_factory=list)

    preprocessing_steps: list[AlgorithmStep] = Field(default_factory=list)
    algorithm_steps: list[AlgorithmStep] = Field(default_factory=list)
    equations: list[str] = Field(default_factory=list)

    initialization: str = ""
    parameters: list[Parameter] = Field(default_factory=list)
    stopping_criteria: str = ""
    postprocessing: list[str] = Field(default_factory=list)

    required_dependencies: list[str] = Field(default_factory=list)
    validation_checks: list[ValidationCheck] = Field(default_factory=list)
    known_failure_modes: list[str] = Field(default_factory=list)
    citations: list[Provenance] = Field(default_factory=list)


_PROVENANCE_SCHEMA = {
    "type": "object",
    "description": "Verbatim evidence from the paper. Omit if the field is inferred.",
    "properties": {
        "quote": {"type": "string", "description": "Exact sentence copied from the paper"},
        "page": {"type": "integer", "description": "1-based page number of the quote"},
    },
    "required": ["quote", "page"],
}

_STEP_SCHEMA = {
    "type": "object",
    "properties": {
        "order": {"type": "integer", "description": "1-based execution order"},
        "operation": {
            "type": "string",
            "description": "Imperative, implementable instruction — what to compute, on what",
        },
        "equation": {
            "type": "string",
            "description": "The governing equation in plain ASCII maths, if the paper gives one",
        },
        "notes": {"type": "string", "description": "Implementation caveats"},
        "inferred": {
            "type": "boolean",
            "description": "true if you supplied this from general knowledge rather than the paper",
        },
        "provenance": _PROVENANCE_SCHEMA,
    },
    "required": ["order", "operation", "inferred"],
}

EMIT_SKILL_TOOL: dict = {
    "name": "emit_skill",
    "description": (
        "Emit the structured, executable skill extracted from the paper. "
        "This is the only way to return your answer."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Short technique name, e.g. 'BCFCM'"},
            "description": {"type": "string", "description": "Two-sentence summary"},
            "intended_task": {
                "type": "string",
                "description": "The analysis task this technique solves",
            },
            "modality": {
                "type": "string",
                "description": "Imaging modality, e.g. MRI, EM, histopathology, X-ray",
            },
            "input_requirements": {
                "type": "array",
                "items": {"type": "string"},
                "description": "What the input data must look like: dimensionality, dtype, range",
            },
            "output_specification": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Exact outputs to produce, with filenames where implied",
            },
            "preprocessing_steps": {"type": "array", "items": _STEP_SCHEMA},
            "algorithm_steps": {
                "type": "array",
                "items": _STEP_SCHEMA,
                "description": (
                    "The core procedure, in execution order. "
                    "Be specific enough to code from."
                ),
            },
            "equations": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Key equations in ASCII, each self-contained",
            },
            "initialization": {
                "type": "string",
                "description": "How to initialise state before iterating",
            },
            "parameters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "name": {"type": "string"},
                        "value": {
                            "type": "string",
                            "description": "Concrete value used in the paper",
                        },
                        "units": {"type": "string"},
                        "role": {"type": "string", "description": "What this parameter controls"},
                        "inferred": {"type": "boolean"},
                        "provenance": _PROVENANCE_SCHEMA,
                    },
                    "required": ["symbol", "value", "inferred"],
                },
            },
            "stopping_criteria": {
                "type": "string",
                "description": "Convergence test and threshold, plus any iteration cap",
            },
            "postprocessing": {"type": "array", "items": {"type": "string"}},
            "required_dependencies": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Python packages needed, e.g. numpy, scipy, nibabel",
            },
            "validation_checks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "expected": {"type": "string"},
                    },
                    "required": ["name"],
                },
                "description": "Self-checks the implementer should run to confirm correctness",
            },
            "known_failure_modes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Ways this technique is known to break, from the paper or experience",
            },
            "citations": {"type": "array", "items": _PROVENANCE_SCHEMA},
        },
        "required": [
            "name", "description", "intended_task", "modality",
            "algorithm_steps", "parameters", "required_dependencies",
        ],
    },
}


def _render_steps(steps: list[AlgorithmStep]) -> str:
    if not steps:
        return "_None specified._\n"
    out = []
    for s in sorted(steps, key=lambda x: x.order):
        tag = " _(inferred)_" if s.inferred else ""
        cite = f" — p.{s.provenance.page}" if s.provenance else ""
        out.append(f"{s.order}. **{s.operation}**{tag}{cite}")
        if s.equation:
            out.append(f"\n   ```\n   {s.equation}\n   ```")
        if s.notes:
            out.append(f"\n   > {s.notes}")
    return "\n".join(out) + "\n"


def skill_to_markdown(skill: Skill) -> str:
    lines: list[str] = [f"# {skill.name}", "", skill.description, ""]
    lines += ["## Intended task", "", skill.intended_task, ""]
    lines += [f"**Modality:** {skill.modality}", ""]

    if skill.input_requirements:
        lines += ["## Input requirements", ""]
        lines += [f"- {x}" for x in skill.input_requirements] + [""]
    if skill.output_specification:
        lines += ["## Outputs", ""]
        lines += [f"- {x}" for x in skill.output_specification] + [""]
    if skill.preprocessing_steps:
        lines += ["## Preprocessing", "", _render_steps(skill.preprocessing_steps)]

    lines += ["## Algorithm", "", _render_steps(skill.algorithm_steps)]

    if skill.initialization:
        lines += ["## Initialization", "", skill.initialization, ""]

    lines += ["## Parameters", ""]
    if skill.parameters:
        lines += ["| Symbol | Value | Role | Source |", "|---|---|---|---|"]
        for p in skill.parameters:
            src = (
                "_inferred_"
                if p.inferred
                else (f"p.{p.provenance.page}" if p.provenance else "—")
            )
            lines.append(f"| `{p.symbol}` | {p.value} {p.units} | {p.role} | {src} |")
        lines.append("")
    else:
        lines += ["_None specified._", ""]

    if skill.stopping_criteria:
        lines += ["## Stopping criteria", "", skill.stopping_criteria, ""]
    if skill.equations:
        lines += ["## Equations", ""] + [f"```\n{e}\n```" for e in skill.equations] + [""]
    if skill.postprocessing:
        lines += ["## Postprocessing", ""] + [f"- {x}" for x in skill.postprocessing] + [""]
    if skill.validation_checks:
        lines += ["## Validation checks", ""]
        lines += [f"- **{c.name}** — {c.description} (expect: {c.expected})"
                  for c in skill.validation_checks] + [""]
    if skill.known_failure_modes:
        lines += ["## Known failure modes", ""]
        lines += [f"- {x}" for x in skill.known_failure_modes] + [""]
    if skill.required_dependencies:
        lines += [
            "## Dependencies",
            "",
            ", ".join(f"`{d}`" for d in skill.required_dependencies),
            "",
        ]

    return "\n".join(lines)
