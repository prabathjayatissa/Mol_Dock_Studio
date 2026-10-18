/**
 * Viewer store: everything that controls *how* the loaded structure is drawn.
 *
 * It is deliberately serialisable so it can support undo/redo: each mutating
 * action snapshots the previous document first. The Three.js engine reads this
 * store and rebuilds only the parts that changed.
 */

import { create } from "zustand";

export type Representation =
  | "lines"
  | "stick"
  | "ball-stick"
  | "spacefill"
  | "backbone"
  | "cartoon";

export type ColorScheme =
  | "element"
  | "chain"
  | "secondary-structure"
  | "residue"
  | "hydropathy"
  | "bfactor";

export type SurfaceMode = "vdw" | "sas";

export type LabelMode = "none" | "residue" | "selected";

export interface Measurement {
  id: string;
  kind: "distance" | "angle";
  atoms: number[];
  value: number;
  label: string;
}

export interface ViewerDocument {
  representation: Representation;
  colorScheme: ColorScheme;
  showHydrogens: boolean;
  showWaters: boolean;
  showSurface: boolean;
  surfaceMode: SurfaceMode;
  surfaceOpacity: number;
  showLabels: boolean;
  labelMode: LabelMode;
  hiddenChains: number[];
  hiddenResidues: number[];
  labelSelectedAtoms: number[];
  background: "dark" | "light";
  measurements: Measurement[];
}

const DEFAULT_DOCUMENT: ViewerDocument = {
  representation: "cartoon",
  colorScheme: "secondary-structure",
  showHydrogens: false,
  showWaters: false,
  showSurface: false,
  surfaceMode: "sas",
  surfaceOpacity: 0.35,
  showLabels: false,
  labelMode: "residue",
  hiddenChains: [],
  hiddenResidues: [],
  labelSelectedAtoms: [],
  background: "dark",
  measurements: [],
};

const HISTORY_LIMIT = 50;

interface ViewerState extends ViewerDocument {
  past: ViewerDocument[];
  future: ViewerDocument[];
  /** Bumped to ask the engine to frame the whole structure. */
  resetNonce: number;

  setRepresentation: (value: Representation) => void;
  setColorScheme: (value: ColorScheme) => void;
  setShowHydrogens: (value: boolean) => void;
  setShowWaters: (value: boolean) => void;
  setShowSurface: (value: boolean) => void;
  setSurfaceMode: (value: SurfaceMode) => void;
  setSurfaceOpacity: (value: number) => void;
  setShowLabels: (value: boolean) => void;
  setLabelMode: (mode: LabelMode) => void;
  setBackground: (value: "dark" | "light") => void;
  hideChain: (chainIndex: number) => void;
  showChain: (chainIndex: number) => void;
  hideResidue: (residueIndex: number) => void;
  showResidue: (residueIndex: number) => void;
  showAll: () => void;
  labelAtom: (atomIndex: number) => void;
  clearLabels: () => void;
  addMeasurement: (measurement: Omit<Measurement, "id">) => void;
  removeMeasurement: (id: string) => void;
  clearMeasurements: () => void;
  requestReset: () => void;
  undo: () => void;
  redo: () => void;
  canUndo: () => boolean;
  canRedo: () => boolean;
}

function snapshot(state: ViewerState): ViewerDocument {
  return {
    representation: state.representation,
    colorScheme: state.colorScheme,
    showHydrogens: state.showHydrogens,
    showWaters: state.showWaters,
    showSurface: state.showSurface,
    surfaceMode: state.surfaceMode,
    surfaceOpacity: state.surfaceOpacity,
    showLabels: state.showLabels,
    labelMode: state.labelMode,
    hiddenChains: state.hiddenChains,
    hiddenResidues: state.hiddenResidues,
    labelSelectedAtoms: state.labelSelectedAtoms,
    background: state.background,
    measurements: state.measurements,
  };
}

/** Push the current document onto the undo stack and apply a change. */
function edit(
  set: (partial: Partial<ViewerState>) => void,
  get: () => ViewerState,
  change: Partial<ViewerDocument>,
): void {
  const state = get();
  const past = [...state.past, snapshot(state)].slice(-HISTORY_LIMIT);
  set({ ...change, past, future: [] });
}

let measurementCounter = 0;
const nextMeasurementId = () => `m${(measurementCounter += 1)}`;

export const useViewerStore = create<ViewerState>()((set, get) => ({
  ...DEFAULT_DOCUMENT,
  past: [],
  future: [],
  resetNonce: 0,

  setRepresentation: (value) => edit(set, get, { representation: value }),
  setColorScheme: (value) => edit(set, get, { colorScheme: value }),
  setShowHydrogens: (value) => edit(set, get, { showHydrogens: value }),
  setShowWaters: (value) => edit(set, get, { showWaters: value }),
  setShowSurface: (value) => edit(set, get, { showSurface: value }),
  setSurfaceMode: (value) => edit(set, get, { surfaceMode: value }),
  setSurfaceOpacity: (value) => set({ surfaceOpacity: Math.min(1, Math.max(0, value)) }),
  setShowLabels: (value) => edit(set, get, { showLabels: value }),
  setLabelMode: (mode) => edit(set, get, { labelMode: mode }),
  setBackground: (value) => edit(set, get, { background: value }),

  hideChain: (chainIndex: number) => {
    const state = get();
    if (state.hiddenChains.includes(chainIndex)) return;
    edit(set, get, { hiddenChains: [...state.hiddenChains, chainIndex] });
  },

  showChain: (chainIndex: number) => {
    const state = get();
    edit(set, get, { hiddenChains: state.hiddenChains.filter((c) => c !== chainIndex) });
  },

  hideResidue: (residueIndex: number) => {
    const state = get();
    if (state.hiddenResidues.includes(residueIndex)) return;
    edit(set, get, { hiddenResidues: [...state.hiddenResidues, residueIndex] });
  },

  showResidue: (residueIndex: number) => {
    const state = get();
    edit(set, get, { hiddenResidues: state.hiddenResidues.filter((r) => r !== residueIndex) });
  },

  showAll: () => edit(set, get, { hiddenChains: [], hiddenResidues: [] }),

  labelAtom: (atomIndex: number) => {
    const state = get();
    if (state.labelSelectedAtoms.includes(atomIndex)) return;
    edit(set, get, {
      labelSelectedAtoms: [...state.labelSelectedAtoms, atomIndex],
      showLabels: true,
      labelMode: "selected",
    });
  },

  clearLabels: () => edit(set, get, { labelSelectedAtoms: [], showLabels: false }),

  addMeasurement: (measurement) =>
    edit(set, get, {
      measurements: [...get().measurements, { ...measurement, id: nextMeasurementId() }],
    }),
  removeMeasurement: (id) =>
    edit(set, get, { measurements: get().measurements.filter((m) => m.id !== id) }),
  clearMeasurements: () => edit(set, get, { measurements: [] }),

  requestReset: () => set({ resetNonce: get().resetNonce + 1 }),

  undo() {
    const { past, future } = get();
    if (past.length === 0) return;
    const previous = past[past.length - 1];
    set({
      ...previous,
      past: past.slice(0, -1),
      future: [snapshot(get()), ...future].slice(0, HISTORY_LIMIT),
    });
  },

  redo() {
    const { past, future } = get();
    if (future.length === 0) return;
    const next = future[0];
    set({
      ...next,
      past: [...past, snapshot(get())].slice(-HISTORY_LIMIT),
      future: future.slice(1),
    });
  },

  canUndo: () => get().past.length > 0,
  canRedo: () => get().future.length > 0,
}));

export { DEFAULT_DOCUMENT };
