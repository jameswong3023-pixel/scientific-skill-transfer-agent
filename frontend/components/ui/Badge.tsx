import clsx from "clsx";

const TONES = {
  neutral: "bg-slate-500/15 text-slate-300 border-slate-500/30",
  good: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  warn: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  bad: "bg-red-500/15 text-red-300 border-red-500/30",
  info: "bg-violet-500/15 text-violet-300 border-violet-500/30",
} as const;

export function Badge({
  tone = "neutral", children, className,
}: { tone?: keyof typeof TONES; children: React.ReactNode; className?: string }) {
  return (
    <span className={clsx("rounded-md border px-2 py-0.5 text-xs font-medium", TONES[tone], className)}>
      {children}
    </span>
  );
}
