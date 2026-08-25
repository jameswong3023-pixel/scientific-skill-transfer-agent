import clsx from "clsx";

import { Panel } from "@/components/ui/Panel";
import { duration, num } from "@/lib/format";
import type { Comparison } from "@/lib/types";

const SYSTEM_ROWS: [string, string, (v: number) => string][] = [
  ["agent_steps", "Agent steps", (v) => String(v)],
  ["code_executions", "Code executions", (v) => String(v)],
  ["failed_executions", "Failed executions", (v) => String(v)],
  ["runtime_seconds", "Runtime", (v) => duration(v)],
  ["total_tokens", "Tokens", (v) => v.toLocaleString()],
  ["cost", "Cost", (v) => `$${v.toFixed(4)}`],
];

export function MetricsTable({ comparison }: { comparison: Comparison }) {
  const quality = comparison.metrics.quality ?? {};
  const system = comparison.metrics.system ?? {};
  const delta = comparison.metrics.comparison?.dice_delta?.value ?? null;

  const baseDice = quality.base?.mean_dice?.value ?? null;
  const skillDice = quality.skill?.mean_dice?.value ?? null;

  const classKeys = Array.from(
    new Set(
      [...Object.keys(quality.base ?? {}), ...Object.keys(quality.skill ?? {})].filter((k) =>
        k.startsWith("dice_class_"),
      ),
    ),
  ).sort();

  return (
    <div className="space-y-4">
      {delta !== null && (
        <Panel title="Did the skill help?">
          <div className="flex flex-wrap items-center gap-8">
            <div>
              <p className="text-xs uppercase tracking-wide text-slate-500">Base mean Dice</p>
              <p className="mt-1 text-3xl font-semibold text-slate-300">{num(baseDice)}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-slate-500">Skill-enabled mean Dice</p>
              <p className="mt-1 text-3xl font-semibold text-violet-300">{num(skillDice)}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-slate-500">Difference</p>
              <p
                className={clsx(
                  "mt-1 text-3xl font-semibold",
                  delta > 0.001 ? "text-emerald-400" : delta < -0.001 ? "text-red-400" : "text-slate-400",
                )}
              >
                {delta > 0 ? "+" : ""}{num(delta)}
              </p>
            </div>
          </div>
        </Panel>
      )}

      {classKeys.length > 0 && (
        <Panel title="Per-class Dice">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="pb-2">Class</th><th className="pb-2">Base</th>
                <th className="pb-2">Skill-enabled</th><th className="pb-2">Δ</th>
              </tr>
            </thead>
            <tbody>
              {classKeys.map((key) => {
                const b = quality.base?.[key]?.value ?? null;
                const s = quality.skill?.[key]?.value ?? null;
                const d = b !== null && s !== null ? s - b : null;
                return (
                  <tr key={key} className="border-b border-[var(--border)]/50">
                    <td className="py-2 text-slate-300">{key.replace("dice_class_", "Class ")}</td>
                    <td className="py-2 text-slate-300">{num(b)}</td>
                    <td className="py-2 text-violet-300">{num(s)}</td>
                    <td className={clsx("py-2", d && d > 0 ? "text-emerald-400" : d && d < 0 ? "text-red-400" : "text-slate-500")}>
                      {d === null ? "—" : `${d > 0 ? "+" : ""}${num(d)}`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Panel>
      )}

      <Panel title="System metrics" subtitle="Both arms used the same model and budget">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--border)] text-left text-xs uppercase tracking-wide text-slate-500">
              <th className="pb-2">Metric</th><th className="pb-2">Base</th><th className="pb-2">Skill-enabled</th>
            </tr>
          </thead>
          <tbody>
            {SYSTEM_ROWS.map(([key, label, fmt]) => {
              const b = system.base?.[key]?.value;
              const s = system.skill?.[key]?.value;
              return (
                <tr key={key} className="border-b border-[var(--border)]/50">
                  <td className="py-2 text-slate-400">{label}</td>
                  <td className="py-2 text-slate-300">{b == null ? "—" : fmt(b)}</td>
                  <td className="py-2 text-violet-300">{s == null ? "—" : fmt(s)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}
