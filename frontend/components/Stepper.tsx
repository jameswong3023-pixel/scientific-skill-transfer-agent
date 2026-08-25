import clsx from "clsx";
import { Check } from "lucide-react";

export function Stepper({ steps, current }: { steps: string[]; current: number }) {
  return (
    <ol className="flex flex-wrap items-center gap-2 text-sm">
      {steps.map((label, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <li key={label} className="flex items-center gap-2">
            <span
              className={clsx(
                "flex h-6 w-6 items-center justify-center rounded-full border text-xs",
                done && "border-emerald-500/50 bg-emerald-500/20 text-emerald-300",
                active && "border-violet-500/60 bg-violet-500/20 text-violet-200",
                !done && !active && "border-[var(--border)] text-slate-500",
              )}
            >
              {done ? <Check size={13} /> : i + 1}
            </span>
            <span className={clsx(active ? "text-slate-100" : "text-slate-400")}>{label}</span>
            {i < steps.length - 1 && <span className="mx-1 text-slate-700">›</span>}
          </li>
        );
      })}
    </ol>
  );
}
