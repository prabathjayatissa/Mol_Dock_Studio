/**
 * Jobs store: server-side background jobs and their progress.
 *
 * Phase 1 uses lightweight polling (the job layer is a real durable queue, so
 * polling is robust and simple); an SSE endpoint can replace the timer later
 * without changing anything the UI depends on.
 */

import { create } from "zustand";

import { ApiError, api } from "../api/client";
import type { Job, JobLog } from "../api/types";

const POLL_MS = 900;

interface JobsState {
  jobs: Job[];
  loading: boolean;
  error: ApiError | null;
  lastLog: JobLog | null;

  refresh: (projectId?: string) => Promise<void>;
  startPolling: (projectId?: string) => void;
  stopPolling: () => void;
  submitSelfTest: (projectId: string | null) => Promise<void>;
  cancel: (id: string) => Promise<void>;
  loadLog: (id: string) => Promise<void>;
}

let timer: ReturnType<typeof setInterval> | null = null;

export const useJobsStore = create<JobsState>()((set, get) => ({
  jobs: [],
  loading: false,
  error: null,
  lastLog: null,

  async refresh(projectId) {
    try {
      const { items } = await api.listJobs(projectId);
      set({ jobs: items, error: null });
    } catch (cause) {
      set({ error: cause instanceof ApiError ? cause : null });
    }
  },

  startPolling(projectId) {
    get().stopPolling();
    void get().refresh(projectId);
    timer = setInterval(() => {
      void get().refresh(projectId);
    }, POLL_MS);
  },

  stopPolling() {
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  },

  async submitSelfTest(projectId) {
    set({ loading: true });
    try {
      await api.selfTest(projectId, 6, 0.4);
      set({ loading: false });
      await get().refresh(projectId ?? undefined);
    } catch (cause) {
      set({ loading: false, error: cause instanceof ApiError ? cause : null });
    }
  },

  async cancel(id) {
    try {
      await api.cancelJob(id);
      await get().refresh();
    } catch (cause) {
      set({ error: cause instanceof ApiError ? cause : null });
    }
  },

  async loadLog(id) {
    try {
      const log = await api.jobLog(id);
      set({ lastLog: log });
    } catch (cause) {
      set({ error: cause instanceof ApiError ? cause : null });
    }
  },
}));
