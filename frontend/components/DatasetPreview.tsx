"use client";

import { SliceViewer } from "@/components/SliceViewer";
import { api } from "@/lib/api";

/**
 * The plan rendered `<SliceViewer baseUrlFor={(axis, i) => …} />` directly from the
 * dataset page, but that page is a Server Component and `SliceViewer` is a Client
 * Component — React Server Components cannot serialize a function prop across that
 * boundary ("Functions cannot be passed directly to Client Components"). This thin
 * client wrapper takes the serializable `fileId` and builds the closure on the client,
 * preserving the plan's intent exactly.
 */
export function DatasetPreview({ fileId }: { fileId: string }) {
  return (
    <SliceViewer baseUrlFor={(axis, index) => api.datasetSliceUrl(fileId, axis, index)} />
  );
}
