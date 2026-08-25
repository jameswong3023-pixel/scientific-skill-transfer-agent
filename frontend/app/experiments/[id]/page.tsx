import { ComparisonView } from "@/components/ComparisonView";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ExperimentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const comparison = await api.getComparison(id);
  return (
    <main className="mx-auto max-w-7xl p-6">
      <ComparisonView initial={comparison} />
    </main>
  );
}
