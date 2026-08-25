import Link from "next/link";

import { DatasetFileUpload } from "@/components/DatasetUpload";
import { DatasetPreview } from "@/components/DatasetPreview";
import { Badge } from "@/components/ui/Badge";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api";
import { bytes } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function DatasetPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const dataset = await api.getDataset(id);
  const files = dataset.files ?? [];
  const preview = files.find((f) => f.role === "input");

  return (
    <main className="mx-auto max-w-6xl space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">{dataset.name}</h1>
          <p className="text-sm text-slate-500">{dataset.modality}</p>
        </div>
        {files.some((f) => f.role === "input") && (
          <Link
            href={`/experiments/new?dataset=${dataset.id}`}
            className="rounded-lg bg-violet-600 px-4 py-2 font-medium text-white hover:bg-violet-500"
          >
            Use in an experiment &rarr;
          </Link>
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
        <div className="space-y-6">
          <Panel title="Add files"><DatasetFileUpload datasetId={dataset.id} /></Panel>
          <Panel title="Files" subtitle={`${files.length} file(s)`}>
            {files.length === 0 ? (
              <p className="text-sm text-slate-500">No files yet.</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[var(--border)] text-left text-xs uppercase tracking-wide text-slate-500">
                    <th className="pb-2">File</th><th className="pb-2">Role</th>
                    <th className="pb-2">Shape</th><th className="pb-2">Size</th>
                  </tr>
                </thead>
                <tbody>
                  {files.map((f) => {
                    const shape = (f.file_metadata as { shape?: number[] }).shape;
                    return (
                      <tr key={f.id} className="border-b border-[var(--border)]/50">
                        <td className="py-2 text-slate-100">{f.filename}</td>
                        <td className="py-2">
                          <Badge tone={f.role === "ground_truth" ? "warn" : "neutral"}>
                            {f.role === "ground_truth" ? "withheld" : f.role}
                          </Badge>
                        </td>
                        <td className="py-2 mono text-xs text-slate-400">
                          {shape ? shape.join(" × ") : "—"}
                        </td>
                        <td className="py-2 text-slate-400">{bytes(f.bytes)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </Panel>
        </div>

        {preview && (
          <Panel title="Preview" subtitle={preview.filename}>
            <DatasetPreview fileId={preview.id} />
          </Panel>
        )}
      </div>
    </main>
  );
}
