import type {
  Comparison, Conversation, Dataset, DatasetFile, Experiment,
  Message, Paper, SkillDetail,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(`API ${status}: ${detail}`);
  }
}

/** Origin used for server-side (React Server Component) fetches only. */
const INTERNAL_API_ORIGIN = process.env.API_ORIGIN ?? "http://api:8000";

/**
 * In the browser every `/api/*` path is same-origin — `next.config.ts` rewrites it
 * to the API service, which is what keeps EventSource/SSE and cookies simple.
 * On the server there is no origin for a relative URL to resolve against
 * (`fetch("/api/papers")` throws "Failed to parse URL"), so server-rendered
 * requests are addressed directly to the API container.
 */
function resolveUrl(path: string): string {
  return typeof window === "undefined" ? `${INTERNAL_API_ORIGIN}${path}` : path;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(resolveUrl(path), { ...init, cache: "no-store" });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown };
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function json(body: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export const api = {
  // papers
  listPapers: () => request<Paper[]>("/api/papers"),
  getPaper: (id: string) => request<Paper>(`/api/papers/${id}`),
  uploadPaper: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Paper>("/api/papers", { method: "POST", body: form });
  },
  extractSkill: (id: string) =>
    request<{ job_id: string }>(`/api/papers/${id}/extract`, { method: "POST" }),
  getSkill: (paperId: string) => request<SkillDetail>(`/api/papers/${paperId}/skill`),
  pageImageUrl: (paperId: string, page: number) => `/api/papers/${paperId}/pages/${page}`,

  // datasets
  listDatasets: () => request<Dataset[]>("/api/datasets"),
  getDataset: (id: string) => request<Dataset>(`/api/datasets/${id}`),
  createDataset: (name: string, modality: string, description = "") =>
    request<Dataset>("/api/datasets", json({ name, modality, description })),
  uploadDatasetFile: (datasetId: string, file: File, role: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("role", role);
    return request<DatasetFile>(`/api/datasets/${datasetId}/files`, {
      method: "POST",
      body: form,
    });
  },
  datasetSliceUrl: (fileId: string, axis: string, index: number) =>
    `/api/datasets/files/${fileId}/slice?axis=${axis}&index=${index}`,

  // experiments
  listExperiments: () => request<Experiment[]>("/api/experiments"),
  createExperiment: (body: {
    dataset_id: string;
    task_prompt: string;
    paper_id?: string | null;
    skill_version_id?: string | null;
  }) => request<Experiment>("/api/experiments", json(body)),
  runExperiment: (id: string) =>
    request<{ job_id: string }>(`/api/experiments/${id}/run`, { method: "POST" }),
  getComparison: (id: string) => request<Comparison>(`/api/experiments/${id}/comparison`),
  downloadUrl: (id: string) => `/api/experiments/${id}/download`,

  // artifacts
  artifactUrl: (id: string) => `/api/artifacts/${id}`,
  artifactSliceUrl: (id: string, axis: string, index: number, cmap = "gray") =>
    `/api/artifacts/${id}/slice?axis=${axis}&index=${index}&cmap=${cmap}`,
  artifactOverlayUrl: (id: string, axis: string, index: number, alpha = 0.55) =>
    `/api/artifacts/${id}/overlay?axis=${axis}&index=${index}&alpha=${alpha}`,

  // conversations
  createConversation: (experimentId: string, title = "Ask the agent") =>
    request<Conversation>("/api/conversations", json({ experiment_id: experimentId, title })),
  getConversation: (id: string) => request<Conversation>(`/api/conversations/${id}`),
  sendMessage: (id: string, content: string) =>
    request<Message>(`/api/conversations/${id}/messages`, json({ content })),
};
