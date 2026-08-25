import { Suspense } from "react";

import { ExperimentLauncher } from "@/components/ExperimentLauncher";
import { Panel } from "@/components/ui/Panel";
import { Stepper } from "@/components/Stepper";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function NewExperimentPage() {
  const [papers, datasets] = await Promise.all([
    api.listPapers().catch(() => []),
    api.listDatasets().catch(() => []),
  ]);

  return (
    <main className="mx-auto max-w-4xl space-y-6 p-6">
      <Stepper steps={["Paper", "Skill", "Dataset", "Experiment"]} current={3} />
      <Panel title="New A/B experiment" subtitle="Base Agent vs Skill-Enabled Agent">
        <Suspense fallback={null}>
          <ExperimentLauncher papers={papers} datasets={datasets} />
        </Suspense>
      </Panel>
    </main>
  );
}
