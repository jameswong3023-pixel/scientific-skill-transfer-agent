import { Download, FileCode2, FileImage, FileJson, FileText } from "lucide-react";

import { api } from "@/lib/api";
import { bytes } from "@/lib/format";
import type { Artifact } from "@/lib/types";

const ICON = {
  code: FileCode2, figure: FileImage, report: FileJson,
  output: FileText, log: FileText,
} as const;

export function ArtifactList({ artifacts }: { artifacts: Artifact[] }) {
  if (artifacts.length === 0) {
    return <p className="text-sm text-slate-600">No artifacts produced.</p>;
  }
  return (
    <ul className="space-y-1">
      {artifacts.map((a) => {
        const Icon = ICON[a.kind] ?? FileText;
        return (
          <li key={a.id}>
            <a
              href={api.artifactUrl(a.id)}
              className="flex items-center gap-2.5 rounded px-2 py-1.5 text-sm hover:bg-white/[0.04]"
            >
              <Icon size={14} className="shrink-0 text-slate-500" />
              <span className="mono min-w-0 flex-1 truncate text-slate-300">{a.path}</span>
              <span className="shrink-0 text-xs text-slate-600">{bytes(a.bytes)}</span>
              <Download size={13} className="shrink-0 text-slate-600" />
            </a>
          </li>
        );
      })}
    </ul>
  );
}
