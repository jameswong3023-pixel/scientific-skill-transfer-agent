"""Deterministic validation of an extracted skill.

The interesting check is provenance: a field claiming to be quoted from the
paper must actually appear in the paper. This turns "the model says it read
this" into something falsifiable, and it is what makes the UI's
"extracted vs inferred" distinction trustworthy rather than decorative.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.agents.skill_extraction.schema import Skill
from app.papers.ingest import ParsedPage, find_quote

MIN_ALGORITHM_STEPS = 3
MAX_INFERRED_RATIO = 0.8


@dataclass
class ValidationIssue:
    severity: str  # "error" | "warning"
    field: str
    message: str


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)
    verified_quotes: int = 0
    unverified_quotes: int = 0
    inferred_ratio: float = 0.0

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "verified_quotes": self.verified_quotes,
            "unverified_quotes": self.unverified_quotes,
            "inferred_ratio": round(self.inferred_ratio, 3),
            "issues": [
                {"severity": i.severity, "field": i.field, "message": i.message}
                for i in self.issues
            ],
        }

    def as_repair_prompt(self) -> str:
        if self.ok and not self.issues:
            return ""
        lines = [
            "Your extracted skill has problems that must be fixed. "
            "Call `emit_skill` again with a corrected version.",
            "",
        ]
        for i in self.issues:
            lines.append(f"- [{i.severity.upper()}] {i.field}: {i.message}")
        lines += [
            "",
            "Rules for the corrected version:",
            "- If you cannot find a verbatim quote in the paper for a claim, set "
            "`inferred: true` and omit `provenance`. Do NOT invent quotes.",
            "- Quotes must be copied exactly from the page you cite.",
            f"- Provide at least {MIN_ALGORITHM_STEPS} algorithm steps, numbered 1..N with no gaps.",
        ]
        return "\n".join(lines)


def _check_provenance(
    report: ValidationReport, pages: list[ParsedPage], field_name: str, item, inferred: bool
) -> None:
    prov = getattr(item, "provenance", None)
    if inferred:
        return
    if prov is None:
        report.issues.append(
            ValidationIssue(
                "warning", field_name,
                "claims to come from the paper but carries no provenance quote",
            )
        )
        return
    found_page = find_quote(prov.quote, pages)
    if found_page is None:
        report.unverified_quotes += 1
        report.issues.append(
            ValidationIssue(
                "error", field_name,
                f"quoted text not found anywhere in the paper: {prov.quote[:120]!r}",
            )
        )
    else:
        report.verified_quotes += 1
        if found_page != prov.page:
            report.issues.append(
                ValidationIssue(
                    "warning", field_name,
                    f"quote cited as page {prov.page} but actually appears on page {found_page}",
                )
            )


def validate_skill(skill: Skill, pages: list[ParsedPage]) -> ValidationReport:
    report = ValidationReport()

    steps = skill.algorithm_steps
    if len(steps) < MIN_ALGORITHM_STEPS:
        report.issues.append(
            ValidationIssue(
                "error", "algorithm_steps",
                f"only {len(steps)} step(s); a usable procedure needs at least "
                f"{MIN_ALGORITHM_STEPS}. Decompose the method into concrete operations.",
            )
        )

    if steps:
        orders = sorted(s.order for s in steps)
        if orders != list(range(1, len(orders) + 1)):
            report.issues.append(
                ValidationIssue(
                    "error", "algorithm_steps",
                    f"step order must be 1..{len(orders)} with no gaps or duplicates, got {orders}",
                )
            )

    for s in steps:
        _check_provenance(report, pages, "algorithm_steps", s, s.inferred)
    for s in skill.preprocessing_steps:
        _check_provenance(report, pages, "preprocessing_steps", s, s.inferred)
    for p in skill.parameters:
        _check_provenance(report, pages, "parameters", p, p.inferred)

    countable = list(steps) + list(skill.parameters)
    if countable:
        report.inferred_ratio = sum(1 for x in countable if x.inferred) / len(countable)
        if report.inferred_ratio > MAX_INFERRED_RATIO:
            report.issues.append(
                ValidationIssue(
                    "warning", "skill",
                    f"{report.inferred_ratio:.0%} of the skill is inferred rather than "
                    f"extracted — the paper may not have been read closely enough",
                )
            )

    if not skill.required_dependencies:
        report.issues.append(
            ValidationIssue("warning", "required_dependencies", "no dependencies listed")
        )
    if not skill.stopping_criteria and any(
        "iterat" in (s.operation or "").lower() for s in steps
    ):
        report.issues.append(
            ValidationIssue(
                "warning", "stopping_criteria",
                "the procedure iterates but no stopping criterion was extracted",
            )
        )

    return report
