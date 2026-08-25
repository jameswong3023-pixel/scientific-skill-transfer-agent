export function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

export function duration(seconds?: number): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  return `${m}m ${Math.round(seconds % 60)}s`;
}

export function pct(x?: number | null, digits = 1): string {
  if (x == null || Number.isNaN(x)) return "—";
  return `${(x * 100).toFixed(digits)}%`;
}

export function num(x?: number | null, digits = 3): string {
  if (x == null || Number.isNaN(x)) return "—";
  return x.toFixed(digits);
}

export const ARM_LABEL: Record<string, string> = {
  base: "Base Agent",
  skill: "Skill-Enabled Agent",
};

export const ARM_STYLE: Record<string, { text: string; bg: string; border: string; dot: string }> = {
  base: {
    text: "text-slate-300", bg: "bg-slate-500/10",
    border: "border-slate-500/40", dot: "bg-slate-400",
  },
  skill: {
    text: "text-violet-300", bg: "bg-violet-500/10",
    border: "border-violet-500/40", dot: "bg-violet-400",
  },
};
