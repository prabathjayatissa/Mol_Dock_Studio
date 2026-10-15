/**
 * Structure store: the single loaded viewer packet, the current selection, and
 * every action that produces a new structure (upload, RCSB fetch, ligand from
 * SMILES). Only one structure is shown at a time in Phase 1.
 */

import { create } from "zustand";

import { ApiError, api } from "../api/client";
import type { ImportResult, StructurePacket } from "../api/types";
import { useSessionStore } from "./sessionStore";

interface StructureState {
  packet: StructurePacket | null;
  loading: boolean;
  error: ApiError | null;

  /** Atom indices currently selected (empty means nothing is selected). */
  selection: Set<number>;
  /** The most recently clicked atom, used as the first point of a measurement. */
  focusAtom: number | null;

  loadPacket: (structureId: string) => Promise<void>;
  clear: () => void;

  setSelection: (atoms: Iterable<number>, additive?: boolean) => void;
  toggleAtom: (index: number) => void;
  selectResidue: (residueIndex: number, additive?: boolean) => void;
  selectChain: (chainIndex: number, additive?: boolean) => void;
  clearSelection: () => void;

  importFile: (
    projectId: string,
    file: File,
    opts?: { kind?: string; format?: string; name?: string; activate?: boolean },
  ) => Promise<ImportResult | null>;
  importLigandFile: (projectId: string, file: File, name?: string) => Promise<ImportResult | null>;
  fetchRcsb: (projectId: string, entryId: string, format?: "pdb" | "mmcif") => Promise<ImportResult | null>;
  ligandFromSmiles: (projectId: string, smiles: string, name?: string) => Promise<ImportResult | null>;
  setError: (error: ApiError | null) => void;
}

async function activate(result: ImportResult): Promise<void> {
  await useSessionStore.getState().refreshStructures();
  await useStructureStore.getState().loadPacket(result.structure.id);
}

export const useStructureStore = create<StructureState>()((set, get) => ({
  packet: null,
  loading: false,
  error: null,
  selection: new Set(),
  focusAtom: null,

  async loadPacket(structureId) {
    set({ loading: true, error: null });
    try {
      const packet = await api.getPacket(structureId);
      set({ packet, loading: false, selection: new Set(), focusAtom: null });
    } catch (cause) {
      set({ loading: false, error: cause instanceof ApiError ? cause : null });
    }
  },

  clear: () => set({ packet: null, selection: new Set(), focusAtom: null, error: null }),

  setSelection(atoms, additive = false) {
    const list = [...atoms];
    const next = additive ? new Set(get().selection) : new Set<number>();
    for (const atom of list) next.add(atom);
    set({ selection: next, focusAtom: additive ? get().focusAtom : (list[0] ?? null) });
  },

  toggleAtom(index) {
    const next = new Set(get().selection);
    if (next.has(index)) {
      next.delete(index);
    } else {
      next.add(index);
    }
    set({ selection: next, focusAtom: index });
  },

  selectResidue(residueIndex, additive = false) {
    const packet = get().packet;
    if (!packet) return;
    const residue = packet.residues[residueIndex];
    if (!residue) return;
    const atoms: number[] = [];
    for (let i = residue.atomStart; i < residue.atomStart + residue.atomCount; i += 1) atoms.push(i);
    get().setSelection(atoms, additive);
  },

  selectChain(chainIndex, additive = false) {
    const packet = get().packet;
    if (!packet) return;
    const atoms = packet.atoms.chainIndex
      .map((chain, index) => (chain === chainIndex ? index : -1))
      .filter((index) => index >= 0);
    get().setSelection(atoms, additive);
  },

  clearSelection: () => set({ selection: new Set(), focusAtom: null }),

  async importFile(projectId, file, opts = {}) {
    set({ loading: true, error: null });
    try {
      const result = await api.importStructure(projectId, file, opts);
      set({ loading: false });
      if (opts.activate !== false) await activate(result);
      return result;
    } catch (cause) {
      set({ loading: false, error: cause instanceof ApiError ? cause : null });
      return null;
    }
  },

  async importLigandFile(projectId, file, name) {
    set({ loading: true, error: null });
    try {
      const result = await api.importLigand(projectId, file, name);
      set({ loading: false });
      await activate(result);
      return result;
    } catch (cause) {
      set({ loading: false, error: cause instanceof ApiError ? cause : null });
      return null;
    }
  },

  async fetchRcsb(projectId, entryId, format = "pdb") {
    set({ loading: true, error: null });
    try {
      const result = await api.fetchRcsb(projectId, entryId.toUpperCase(), format);
      set({ loading: false });
      await activate(result);
      return result;
    } catch (cause) {
      set({ loading: false, error: cause instanceof ApiError ? cause : null });
      return null;
    }
  },

  async ligandFromSmiles(projectId, smiles, name = "Ligand") {
    set({ loading: true, error: null });
    try {
      const result = await api.ligandFromSmiles(projectId, smiles, name);
      set({ loading: false });
      await activate(result);
      return result;
    } catch (cause) {
      set({ loading: false, error: cause instanceof ApiError ? cause : null });
      return null;
    }
  },

  setError: (error) => set({ error }),
}));
