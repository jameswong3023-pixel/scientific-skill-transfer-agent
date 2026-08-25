import Link from "next/link";

import { SkillInspector } from "@/components/SkillInspector";
import { PaperStatusWatcher } from "@/components/PaperStatusWatcher";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function PaperPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const paper = await api.getPaper(id);
  const skill = await api.getSkill(id).catch(() => null);

  return (
    <main className="mx-auto max-w-5xl space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">{paper.title ?? paper.filename}</h1>
          <p className="text-sm text-slate-500">{paper.page_count} pages</p>
        </div>
        {skill && (
          <Link
            href={`/experiments/new?paper=${paper.id}&skill=${skill.id}`}
            className="rounded-lg bg-violet-600 px-4 py-2 font-medium text-white hover:bg-violet-500"
          >
            Run an A/B experiment &rarr;
          </Link>
        )}
      </div>

      {!skill ? (
        <Panel title="Extracting the skill">
          <PaperStatusWatcher paperId={paper.id} initialStatus={paper.status} />
        </Panel>
      ) : (
        <SkillInspector skill={skill} />
      )}
    </main>
  );
}
