import Link from "next/link";

import { PaperUpload } from "@/components/PaperUpload";
import { Panel } from "@/components/ui/Panel";
import { StatusPill } from "@/components/ui/StatusPill";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function PapersPage() {
  const papers = await api.listPapers().catch(() => []);
  return (
    <main className="mx-auto max-w-5xl space-y-6 p-6">
      <h1 className="text-2xl font-semibold text-slate-100">Papers</h1>
      <Panel title="Upload a paper">
        <PaperUpload />
      </Panel>
      <Panel title="Library" subtitle={`${papers.length} paper(s)`}>
        {papers.length === 0 ? (
          <p className="text-sm text-slate-500">Nothing uploaded yet.</p>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {papers.map((p) => (
              <li key={p.id} className="flex items-center justify-between py-3">
                <Link href={`/papers/${p.id}`} className="min-w-0 flex-1 hover:text-violet-300">
                  <p className="truncate text-slate-100">{p.title ?? p.filename}</p>
                  <p className="text-xs text-slate-500">{p.page_count} pages · {p.filename}</p>
                </Link>
                <StatusPill status={p.status} />
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </main>
  );
}
