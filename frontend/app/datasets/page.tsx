import Link from "next/link";

import { DatasetCreate } from "@/components/DatasetUpload";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function DatasetsPage() {
  const datasets = await api.listDatasets().catch(() => []);
  return (
    <main className="mx-auto max-w-5xl space-y-6 p-6">
      <h1 className="text-2xl font-semibold text-slate-100">Datasets</h1>
      <Panel title="New dataset"><DatasetCreate /></Panel>
      <Panel title="Available datasets">
        {datasets.length === 0 ? (
          <p className="text-sm text-slate-500">No datasets yet.</p>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {datasets.map((d) => (
              <li key={d.id} className="py-3">
                <Link href={`/datasets/${d.id}`} className="hover:text-violet-300">
                  <p className="text-slate-100">{d.name}</p>
                  <p className="text-xs text-slate-500">{d.modality}</p>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </main>
  );
}
