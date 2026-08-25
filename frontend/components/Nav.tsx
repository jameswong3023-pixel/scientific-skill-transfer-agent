import Link from "next/link";
import { FlaskConical } from "lucide-react";

export function Nav() {
  return (
    // NOTE: the plan wrote `backdrop--blur` (double hyphen), which is not a real
    // Tailwind utility and silently produced no blur. Corrected to `backdrop-blur`.
    <header className="border-b border-[var(--border)] bg-[var(--panel)]/60 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3">
        <Link href="/" className="flex items-center gap-2.5 font-semibold text-slate-100">
          <FlaskConical size={18} className="text-violet-400" />
          Scientific Skill Transfer Agent
        </Link>
        <nav className="flex gap-5 text-sm text-slate-400">
          <Link href="/papers" className="hover:text-slate-100">Papers</Link>
          <Link href="/datasets" className="hover:text-slate-100">Datasets</Link>
          <Link href="/experiments" className="hover:text-slate-100">Experiments</Link>
        </nav>
      </div>
    </header>
  );
}
