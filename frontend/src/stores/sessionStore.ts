/**
 * Session store: the health/capability report, the project list and the
 * per-project structure list. Everything here is server state that survives a
 * reload; the UI never invents it.
 */

import { create } from "zustand";

import { ApiError, api } from "../api/client";
import type { Health, Project, StructureSummary } from "../api/types";

interface SessionState {
  health: Health | null;
  healthLoading: boolean;
  healthError: string | null;

  projects: Project[];
  activeProjectId: string | null;
  structures: StructureSummary[];

  loading: boolean;
  error: ApiError | null;

  loadHealth: () => Promise<void>;
  loadProjects: () => Promise<void>;
  createProject: (name: string, description?: string) => Promise<Project | null>;
  selectProject: (id: string | null) => Promise<void>;
  refreshStructures: () => Promise<void>;
  clearError: () => void;
  capability: (key: string) => Health["capabilities"][number] | undefined;
}

export const useSessionStore = create<SessionState>()((set, get) => ({
  health: null,
  healthLoading: false,
  healthError: null,

  projects: [],
  activeProjectId: null,
  structures: [],

  loading: false,
  error: null,

  async loadHealth() {
    set({ healthLoading: true, healthError: null });
    try {
      const health = await api.health();
      set({ health, healthLoading: false });
    } catch (cause) {
      const message = cause instanceof ApiError ? cause.message : String(cause);
      set({ healthError: message, healthLoading: false });
    }
  },

  async loadProjects() {
    set({ loading: true, error: null });
    try {
      const { items } = await api.listProjects();
      const current = get().activeProjectId;
      const stillExists = current && items.some((p) => p.id === current);
      const activeProjectId = stillExists ? current : (items[0]?.id ?? null);
      set({ projects: items, activeProjectId, loading: false });
      if (activeProjectId) {
        await get().refreshStructures();
      } else {
        set({ structures: [] });
      }
    } catch (cause) {
      set({ loading: false, error: cause instanceof ApiError ? cause : null });
    }
  },

  async createProject(name, description = "") {
    set({ loading: true, error: null });
    try {
      const project = await api.createProject(name, description);
      set((state) => ({
        projects: [...state.projects, project],
        activeProjectId: project.id,
        structures: [],
        loading: false,
      }));
      return project;
    } catch (cause) {
      set({ loading: false, error: cause instanceof ApiError ? cause : null });
      return null;
    }
  },

  async selectProject(id) {
    set({ activeProjectId: id, structures: [] });
    if (id) await get().refreshStructures();
  },

  async refreshStructures() {
    const projectId = get().activeProjectId;
    if (!projectId) {
      set({ structures: [] });
      return;
    }
    try {
      const { items } = await api.listStructures(projectId);
      set({ structures: items });
    } catch (cause) {
      set({ error: cause instanceof ApiError ? cause : null });
    }
  },

  clearError: () => set({ error: null }),

  capability(key) {
    return get().health?.capabilities.find((c) => c.key === key);
  },
}));
