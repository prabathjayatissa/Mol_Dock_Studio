/**
 * Atom/residue colouring schemes.
 *
 * These are pure functions over a structure packet so they can be unit-tested
 * without a WebGL context. Colours are returned as `[r, g, b]` in 0..1.
 */

import type { ColorScheme } from "../stores/viewerStore";
import type { PacketResidue, StructurePacket } from "../api/types";

export type RGB = [number, number, number];

/** Fallback CPK colours for the (rare) element the backend does not know. */
const FALLBACK_ELEMENT_COLOR: Record<string, RGB> = {
  H: [1, 1, 1],
  C: [0.5, 0.5, 0.5],
  N: [0.19, 0.31, 0.97],
  O: [1, 0.05, 0.05],
  S: [1, 0.78, 0.2],
  P: [1, 0.5, 0],
};

/** A small, colour-blind-reasonable palette for chains. */
export const CHAIN_PALETTE: RGB[] = [
  [0.29, 0.6, 0.98],
  [0.98, 0.55, 0.29],
  [0.36, 0.82, 0.5],
  [0.85, 0.4, 0.75],
  [0.98, 0.85, 0.3],
  [0.5, 0.8, 0.9],
  [0.75, 0.55, 0.95],
  [0.6, 0.6, 0.6],
];

/** Secondary-structure colours, matching the common red/yellow/grey convention. */
export const SS_COLORS: Record<string, RGB> = {
  H: [0.9, 0.25, 0.25],
  E: [0.95, 0.8, 0.2],
  C: [0.62, 0.62, 0.66],
};

function hexToRgb(hex: string): RGB | null {
  const match = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!match) return null;
  const value = parseInt(match[1], 16);
  return [((value >> 16) & 255) / 255, ((value >> 8) & 255) / 255, (value & 255) / 255];
}

function hslToRgb(h: number, s: number, l: number): RGB {
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const hp = h / 60;
  const x = c * (1 - Math.abs((hp % 2) - 1));
  let r = 0;
  let g = 0;
  let b = 0;
  if (hp < 1) [r, g, b] = [c, x, 0];
  else if (hp < 2) [r, g, b] = [x, c, 0];
  else if (hp < 3) [r, g, b] = [0, c, x];
  else if (hp < 4) [r, g, b] = [0, x, c];
  else if (hp < 5) [r, g, b] = [x, 0, c];
  else [r, g, b] = [c, 0, x];
  const m = l - c / 2;
  return [r + m, g + m, b + m];
}

/** Blue (hydrophilic, negative) → white → orange (hydrophobic, positive). */
function hydropathyColor(value: number): RGB {
  const t = Math.max(-4.5, Math.min(4.5, value)) / 4.5; // -1 .. 1
  if (t < 0) {
    const k = -t;
    return [1 - 0.6 * k, 1 - 0.35 * k, 1];
  }
  return [1, 1 - 0.45 * t, 1 - 0.75 * t];
}

export interface ColoringContext {
  packet: StructurePacket;
  scheme: ColorScheme;
  /** min/max B-factor over the currently visible atoms. */
  bfactorRange: [number, number];
}

export function buildColoringContext(packet: StructurePacket, scheme: ColorScheme): ColoringContext {
  let min = Infinity;
  let max = -Infinity;
  for (const value of packet.atoms.bfactor) {
    if (value < min) min = value;
    if (value > max) max = value;
  }
  if (!Number.isFinite(min) || !Number.isFinite(max) || max - min < 1e-6) {
    min = 0;
    max = 1;
  }
  return { packet, scheme, bfactorRange: [min, max] };
}

export function atomColor(context: ColoringContext, atomIndex: number): RGB {
  const { packet, scheme } = context;
  const residueIndex = packet.atoms.residueIndex[atomIndex];
  const residue: PacketResidue | undefined = packet.residues[residueIndex];

  switch (scheme) {
    case "element": {
      const parsed = hexToRgb(packet.atoms.color[atomIndex] ?? "");
      if (parsed) return parsed;
      const element = packet.atoms.element[atomIndex] ?? "C";
      return FALLBACK_ELEMENT_COLOR[element] ?? FALLBACK_ELEMENT_COLOR.C;
    }
    case "chain": {
      const chain = packet.atoms.chainIndex[atomIndex] ?? 0;
      return CHAIN_PALETTE[chain % CHAIN_PALETTE.length];
    }
    case "secondary-structure":
      return SS_COLORS[residue?.ss ?? "C"] ?? SS_COLORS.C;
    case "residue":
      return hslToRgb(((residueIndex * 47) % 360), 0.65, 0.6);
    case "hydropathy":
      return hydropathyColor(residue?.hydropathy ?? 0);
    case "bfactor": {
      const [min, max] = context.bfactorRange;
      const t = (packet.atoms.bfactor[atomIndex] - min) / (max - min);
      return hslToRgb((1 - Math.max(0, Math.min(1, t))) * 240, 0.85, 0.55);
    }
    default:
      return FALLBACK_ELEMENT_COLOR.C;
  }
}

/** Colour for a whole residue (used by the cartoon ribbon). */
export function residueColor(context: ColoringContext, residueIndex: number): RGB {
  const residue = context.packet.residues[residueIndex];
  if (!residue) return SS_COLORS.C;
  if (context.scheme === "hydropathy") return hydropathyColor(residue.hydropathy);
  if (context.scheme === "chain") return CHAIN_PALETTE[residue.chainIndex % CHAIN_PALETTE.length];
  if (context.scheme === "residue") return hslToRgb((residueIndex * 47) % 360, 0.65, 0.6);
  if (context.scheme === "secondary-structure" || context.scheme === "element" || context.scheme === "bfactor") {
    return SS_COLORS[residue.ss] ?? SS_COLORS.C;
  }
  return SS_COLORS[residue.ss] ?? SS_COLORS.C;
}

/** Whether an atom passes the global visibility filters. */
export function atomVisible(
  packet: StructurePacket,
  atomIndex: number,
  opts: {
    showHydrogens: boolean;
    showWaters: boolean;
    hiddenChains: number[];
    hiddenResidues: number[];
  },
): boolean {
  if (!opts.showHydrogens && packet.atoms.element[atomIndex] === "H") return false;
  if (!opts.showWaters && packet.atoms.isWater[atomIndex]) return false;
  const residueIndex = packet.atoms.residueIndex[atomIndex];
  const residue = packet.residues[residueIndex];
  if (residue && opts.hiddenResidues.includes(residueIndex)) return false;
  if (residue && opts.hiddenChains.includes(residue.chainIndex)) return false;
  return true;
}
