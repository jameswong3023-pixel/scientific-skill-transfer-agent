import Link from "next/link";

import { Panel } from "@/components/ui/Panel";
import { StatusPill } from "@/components/ui/StatusPill";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ExperimentsPage() {
  const experiments = await api.listExperiments().catch(() => []);
  return (
    <main className="mx-auto max-w-5xl space-y-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-100">Experiments</h1>
        <Link
          href="/experiments/new"
          className="rounded-lg bg-violet-600 px-4 py-2 font-medium text-white hover:bg-violet-500"
        >
          New experiment
        </Link>
      </div>
      <Panel>
        {experiments.length === 0 ? (
          <p className="text-sm text-slate-500">No experiments yet.</p>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {experiments.map((e) => (
              <li key={e.id} className="flex items-center justify-between gap-4 py-3">
                <Link href={`/experiments/${e.id}`} className="min-w-0 flex-1 hover:text-violet-300">
                  <p className="truncate text-slate-200">{e.task_prompt}</p>
                  <p className="text-xs text-slate-500">
                    {new Date(e.created_at).toLocaleString()}
                  </p>
                </Link>
                <StatusPill status={e.status} />
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </main>
  );
}
