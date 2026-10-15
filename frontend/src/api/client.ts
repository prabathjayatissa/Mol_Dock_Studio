/**
 * Thin typed wrapper around fetch.
 *
 * Two rules keep the UI honest:
 *  1. A non-2xx response is turned into an {@link ApiError} carrying the server's
 *     error envelope (code, message, detail, remediation) — never a raw status.
 *  2. Nothing here retries or swallows errors; the caller decides what to show.
 */

import type {
  ApiErrorBody,
  Health,
  ImportResult,
  Job,
  JobList,
  JobLog,
  Ligand,
  Project,
  ProjectList,
  StructureDetail,
  StructureList,
  StructurePacket,
  SurfacePayload,
} from "./types";

const BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail?: Record<string, unknown>;
  readonly remediation?: string;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message || `Request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code ?? "unknown";
    this.detail = body.detail;
    this.remediation = body.remediation;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      headers: { Accept: "application/json", ...(init?.headers ?? {}) },
      ...init,
    });
  } catch (cause) {
    throw new ApiError(0, {
      code: "network_error",
      message:
        "Could not reach the MolDock Studio backend. Is the API server running on port 8000?",
      remediation: "Start it with `make dev-backend` and check /api/health.",
      detail: { cause: String(cause) },
    });
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  const payload = text ? (JSON.parse(text) as unknown) : undefined;

  if (!response.ok) {
    const envelope = (payload as { error?: ApiErrorBody } | undefined)?.error;
    throw new ApiError(
      response.status,
      envelope ?? { code: "http_error", message: `Request failed (${response.status}).` },
    );
  }
  return payload as T;
}

function jsonInit(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export const api = {
  health: () => request<Health>("/health"),

  // --- projects -----------------------------------------------------------
  listProjects: () => request<ProjectList>("/projects"),
  getProject: (id: string) => request<Project>(`/projects/${id}`),
  createProject: (name: string, description = "") =>
    request<Project>("/projects", jsonInit("POST", { name, description })),
  updateProject: (id: string, patch: Partial<Pick<Project, "name" | "description">>) =>
    request<Project>(`/projects/${id}`, jsonInit("PATCH", patch)),
  deleteProject: (id: string) => request<void>(`/projects/${id}`, { method: "DELETE" }),

  // --- structures ---------------------------------------------------------
  listStructures: (projectId: string, kind?: string) => {
    const params = new URLSearchParams({ projectId });
    if (kind) params.set("kind", kind);
    return request<StructureList>(`/structures?${params.toString()}`);
  },
  getStructure: (id: string) => request<StructureDetail>(`/structures/${id}`),
  getPacket: (id: string) => request<StructurePacket>(`/structures/${id}/packet`),
  deleteStructure: (id: string) => request<void>(`/structures/${id}`, { method: "DELETE" }),

  importStructure: (projectId: string, file: File, opts: { kind?: string; format?: string; name?: string } = {}) => {
    const form = new FormData();
    form.append("file", file);
    form.append("projectId", projectId);
    if (opts.kind) form.append("kind", opts.kind);
    if (opts.format) form.append("format", opts.format);
    if (opts.name) form.append("name", opts.name);
    return request<ImportResult>("/structures/import", { method: "POST", body: form });
  },

  fetchRcsb: (projectId: string, entryId: string, format: "pdb" | "mmcif" = "pdb") =>
    request<ImportResult>("/structures/fetch-rcsb", jsonInit("POST", { projectId, entryId, format })),

  importLigand: (projectId: string, file: File, name?: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("projectId", projectId);
    if (name) form.append("name", name);
    return request<ImportResult>("/ligands/import", { method: "POST", body: form });
  },

  ligandFromSmiles: (projectId: string, smiles: string, name = "Ligand", embed3d = true) =>
    request<ImportResult>(
      "/ligands/from-smiles",
      jsonInit("POST", { projectId, smiles, name, embed3d }),
    ),

  listLigands: (projectId: string) =>
    request<{ items: Ligand[]; total: number }>(`/ligands?projectId=${encodeURIComponent(projectId)}`),
  getLigand: (id: string) => request<Ligand>(`/ligands/${id}`),

  exportUrl: (id: string, format: string) =>
    `${BASE}/structures/${id}/export?format=${encodeURIComponent(format)}`,

  // --- surfaces -----------------------------------------------------------
  getSurface: (id: string, opts: { mode?: string; probeRadius?: number; gridSpacing?: number; useCache?: boolean } = {}) => {
    const params = new URLSearchParams();
    if (opts.mode) params.set("mode", opts.mode);
    if (opts.probeRadius !== undefined) params.set("probeRadius", String(opts.probeRadius));
    if (opts.gridSpacing !== undefined) params.set("gridSpacing", String(opts.gridSpacing));
    if (opts.useCache !== undefined) params.set("useCache", String(opts.useCache));
    return request<SurfacePayload>(`/structures/${id}/surface?${params.toString()}`);
  },

  // --- jobs ---------------------------------------------------------------
  listJobs: (projectId?: string) => {
    const params = new URLSearchParams();
    if (projectId) params.set("projectId", projectId);
    return request<JobList>(`/jobs?${params.toString()}`);
  },
  getJob: (id: string) => request<Job>(`/jobs/${id}`),
  cancelJob: (id: string) => request<{ jobId: string; state: string; message: string }>(`/jobs/${id}/cancel`, { method: "POST" }),
  jobLog: (id: string) => request<JobLog>(`/jobs/${id}/log`),
  selfTest: (projectId: string | null, steps = 5, secondsPerStep = 0.4) =>
    request<Job>("/jobs/self-test", jsonInit("POST", { projectId, steps, secondsPerStep })),
};

/** Fetch the raw text of an export for the in-app preview / download. */
export async function fetchExport(id: string, format: string): Promise<string> {
  const response = await fetch(api.exportUrl(id, format));
  if (!response.ok) {
    const body = (await response.json().catch(() => undefined)) as { error?: ApiErrorBody } | undefined;
    throw new ApiError(response.status, body?.error ?? { code: "http_error", message: "Export failed." });
  }
  return response.text();
}
