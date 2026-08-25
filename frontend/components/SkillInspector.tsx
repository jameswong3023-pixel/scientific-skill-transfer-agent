"use client";

import { AlertTriangle, CheckCircle2 } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { Panel } from "@/components/ui/Panel";
import { ProvenanceTag } from "@/components/ProvenancePopover";
import { pct } from "@/lib/format";
import type { AlgorithmStep, SkillDetail } from "@/lib/types";

function Steps({ steps, paperId }: { steps: AlgorithmStep[]; paperId: string | null }) {
  if (steps.length === 0) return <p className="text-sm text-slate-500">None specified.</p>;
  return (
    <ol className="space-y-3">
      {[...steps].sort((a, b) => a.order - b.order).map((step) => (
        <li key={step.order} className="flex gap-3">
          <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-[var(--border)] text-xs text-slate-400">
            {step.order}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-slate-100">{step.operation}</span>
              <ProvenanceTag
                provenance={step.provenance}
                inferred={step.inferred}
                paperId={paperId}
              />
            </div>
            {step.equation && (
              <pre className="mono mt-2 overflow-x-auto rounded bg-black/40 p-2 text-xs text-cyan-300">
                {step.equation}
              </pre>
            )}
            {step.notes && <p className="mt-1 text-sm text-slate-400">{step.notes}</p>}
          </div>
        </li>
      ))}
    </ol>
  );
}

export function SkillInspector({ skill }: { skill: SkillDetail }) {
  const s = skill.payload;
  const v = skill.validation;
  const paperId = skill.paper_id;
  // The plan wrote `v?.issues?.length > 0`, which does not typecheck under strict
  // mode (the operand is `number | undefined`). Same intent, guarded.
  const issues = v?.issues ?? [];

  return (
    <div className="space-y-4">
      <Panel
        title={s.name}
        subtitle={s.description}
        actions={
          <div className="flex items-center gap-2">
            <Badge tone="info">v{skill.version}</Badge>
            <Badge tone={v?.ok ? "good" : "warn"}>
              {v?.ok ? <CheckCircle2 size={12} className="inline" /> : <AlertTriangle size={12} className="inline" />}
              {" "}{v?.ok ? "validated" : "has warnings"}
            </Badge>
          </div>
        }
      >
        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <p className="text-xs uppercase tracking-wide text-slate-500">Intended task</p>
            <p className="mt-1 text-sm text-slate-200">{s.intended_task}</p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-slate-500">Modality</p>
            <p className="mt-1 text-sm text-slate-200">{s.modality}</p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-slate-500">Provenance</p>
            <p className="mt-1 text-sm text-slate-200">
              {v?.verified_quotes ?? 0} quotes verified against the PDF
              {v?.unverified_quotes ? `, ${v.unverified_quotes} unverified` : ""}
              {" · "}
              {pct(v?.inferred_ratio, 0)} inferred
            </p>
          </div>
        </div>
      </Panel>

      {s.preprocessing_steps.length > 0 && (
        <Panel title="Preprocessing">
          <Steps steps={s.preprocessing_steps} paperId={paperId} />
        </Panel>
      )}

      <Panel title="Algorithm" subtitle="The procedure the skill-enabled agent will follow">
        <Steps steps={s.algorithm_steps} paperId={paperId} />
      </Panel>

      <Panel title="Parameters">
        {s.parameters.length === 0 ? (
          <p className="text-sm text-slate-500">None extracted.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="pb-2">Symbol</th>
                <th className="pb-2">Value</th>
                <th className="pb-2">Role</th>
                <th className="pb-2">Source</th>
              </tr>
            </thead>
            <tbody>
              {s.parameters.map((p) => (
                <tr key={p.symbol} className="border-b border-[var(--border)]/50">
                  <td className="py-2 mono text-cyan-300">{p.symbol}</td>
                  <td className="py-2 text-slate-100">{p.value} {p.units}</td>
                  <td className="py-2 text-slate-400">{p.role ?? p.name}</td>
                  <td className="py-2">
                    <ProvenanceTag provenance={p.provenance} inferred={p.inferred} paperId={paperId} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <div className="grid gap-4 md:grid-cols-2">
        <Panel title="Stopping criteria">
          <p className="text-sm text-slate-200">{s.stopping_criteria || "—"}</p>
        </Panel>
        <Panel title="Dependencies">
          <div className="flex flex-wrap gap-1.5">
            {s.required_dependencies.map((d) => (
              <span key={d} className="mono rounded bg-black/40 px-2 py-0.5 text-xs text-slate-300">{d}</span>
            ))}
          </div>
        </Panel>
      </div>

      {s.known_failure_modes.length > 0 && (
        <Panel title="Known failure modes">
          <ul className="list-disc space-y-1 pl-5 text-sm text-slate-300">
            {s.known_failure_modes.map((f, i) => <li key={i}>{f}</li>)}
          </ul>
        </Panel>
      )}

      {issues.length > 0 && (
        <Panel title="Validation notes" subtitle="Automated checks against the source PDF">
          <ul className="space-y-1.5 text-sm">
            {issues.map((issue, i) => (
              <li key={i} className="flex gap-2">
                <Badge tone={issue.severity === "error" ? "bad" : "warn"}>{issue.severity}</Badge>
                <span className="text-slate-300">
                  <span className="mono text-slate-500">{issue.field}</span> — {issue.message}
                </span>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </div>
  );
}
