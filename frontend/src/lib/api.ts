import type {
  DiscoverResponse,
  IngestResult,
  Paper,
  PaperList,
  SearchHit,
  SearchMode,
  SearchResponse,
  Stats,
  TopicCount,
} from "./types";

// Same-origin in dev (Vite proxies /api); VITE_API_BASE points at the API in
// any other deployment.
const BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function responseError(response: Response): Promise<ApiError> {
  // FastAPI returns {detail: ...}; fall back to the status line.
  let detail = `${response.status} ${response.statusText}`;
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") detail = body.detail;
    else if (Array.isArray(body?.detail)) detail = body.detail[0]?.msg ?? detail;
  } catch {
    /* body was not JSON */
  }
  return new ApiError(detail, response.status);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError("Cannot reach the ResearchLens API.", 0);
  }

  if (!response.ok) {
    throw await responseError(response);
  }

  return (await response.json()) as T;
}

export const api = {
  health: () =>
    request<{
      status: string;
      mongodb: boolean;
      search_backend: string;
      embedding_model: string;
      embedding_dim: number;
      papers: number;
      embedded: number;
    }>("/api/health"),

  stats: () => request<Stats>("/api/stats"),

  /** One call per search: local ranking, live fetch when coverage is thin, grouped recommendations. */
  discover: (
    q: string,
    mode: SearchMode,
    opts: { limit?: number; live?: boolean; signal?: AbortSignal } = {},
  ) => {
    const params = new URLSearchParams({
      q,
      mode,
      limit: String(opts.limit ?? 25),
      live: String(opts.live ?? true),
    });
    return request<DiscoverResponse>(`/api/discover?${params.toString()}`, {
      signal: opts.signal,
    });
  },

  search: (q: string, mode: SearchMode, limit = 25, signal?: AbortSignal) =>
    request<SearchResponse>(
      `/api/search?q=${encodeURIComponent(q)}&mode=${mode}&limit=${limit}`,
      { signal },
    ),

  papers: (params: {
    limit?: number;
    offset?: number;
    source?: string;
    topic?: string;
    sort?: "date" | "citations" | "added";
  } = {}) => {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== "") search.set(key, String(value));
    });
    return request<PaperList>(`/api/papers?${search.toString()}`);
  },

  paper: (id: string) => request<Paper>(`/api/papers/${id}`),

  similar: (id: string, limit = 8) =>
    request<SearchHit[]>(`/api/papers/${id}/similar?limit=${limit}`),

  topics: (limit = 24) => request<TopicCount[]>(`/api/papers/topics?limit=${limit}`),

  sources: () => request<string[]>("/api/ingest/sources"),

  /** Can this paper be read in-page? Answered without fetching the file. */
  fileInfo: (id: string) =>
    request<{
      paper_id: string;
      available: boolean;
      filename: string;
      view_url: string;
      download_url: string;
      external_url: string | null;
    }>(`/api/papers/${id}/file-info`),

  /** Streamed through the API so the PDF renders in-page and downloads without a detour. */
  fileUrl: (id: string, download = false) =>
    `${BASE}/api/papers/${id}/file${download ? "?download=true" : ""}`,

  /**
   * Fetch before saving. A normal anchor with `download` will happily save a
   * JSON 404/502 response as a .pdf; this only creates a file for real PDFs.
   */
  downloadFile: async (id: string) => {
    let response: Response;
    try {
      response = await fetch(`${BASE}/api/papers/${id}/file?download=true`);
    } catch {
      throw new ApiError("Cannot reach the ResearchLens API.", 0);
    }
    if (!response.ok) throw await responseError(response);

    const contentType = (response.headers.get("content-type") ?? "").toLowerCase();
    if (!contentType.startsWith("application/pdf")) {
      throw new ApiError("The source did not return a PDF, so no file was downloaded.", 415);
    }

    const file = await response.blob();
    if (file.size === 0) throw new ApiError("The source returned an empty PDF.", 502);

    const disposition = response.headers.get("content-disposition") ?? "";
    const matchedName = disposition.match(/filename="?([^";]+)"?/i)?.[1];
    const link = document.createElement("a");
    const objectUrl = URL.createObjectURL(file);
    link.href = objectUrl;
    link.download = matchedName ?? "paper.pdf";
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(objectUrl);
  },

  ingest: (body: { query: string; sources?: string[]; limit_per_source?: number }) =>
    request<IngestResult>("/api/ingest", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
