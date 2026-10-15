/**
 * Per-representation geometry planning.
 *
 * This module decides, for the current representation and visibility filters,
 * which atoms are drawn and at what radius, and which bonds become lines or
 * cylinders. It returns plain typed arrays (no Three.js objects) so it is cheap
 * to recompute whenever a setting changes.
 *
 * Small molecules (ligands, ions) are always drawn ball-and-stick even in
 * cartoon/backbone mode, so a bound ligand is never invisible.
 */

import type { StructurePacket } from "../api/types";
import type { Representation } from "../stores/viewerStore";
import { atomColor, atomVisible, type ColoringContext } from "./coloring";

export interface AtomStyle {
  /** World-space atom coordinates, flat [x,y,z,...]. */
  positions: Float32Array;
  /** Display radius per atom (0 means "not drawn"). */
  radii: Float32Array;
  /** Pick radius per atom (0 means "not pickable"). */
  pickRadii: Float32Array;
  /** rgb per atom. */
  colors: Float32Array;
  /** 1 where the atom passes the visibility filters. */
  visible: Uint8Array;
}

export interface BondPlan {
  a: Uint32Array;
  b: Uint32Array;
  /** "none" means bonds are not drawn for this representation. */
  mode: "none" | "lines" | "cylinders";
  radius: number;
}

export interface VisibilityOptions {
  showHydrogens: boolean;
  showWaters: boolean;
}

type PolymerMode = "none" | "vanDerWaals" | "ball" | "stick" | "tiny";

interface Plan {
  polymer: PolymerMode;
  bonds: BondPlan["mode"];
  bondRadius: number;
}

export function representationPlan(representation: Representation): Plan {
  switch (representation) {
    case "lines":
      return { polymer: "none", bonds: "lines", bondRadius: 0 };
    case "stick":
      return { polymer: "stick", bonds: "cylinders", bondRadius: 0.15 };
    case "ball-stick":
      return { polymer: "ball", bonds: "cylinders", bondRadius: 0.12 };
    case "spacefill":
      return { polymer: "vanDerWaals", bonds: "none", bondRadius: 0 };
    case "backbone":
      return { polymer: "tiny", bonds: "none", bondRadius: 0 };
    case "cartoon":
    default:
      return { polymer: "none", bonds: "none", bondRadius: 0 };
  }
}

function isPolymerResidue(packet: StructurePacket, residueIndex: number): boolean {
  const residue = packet.residues[residueIndex];
  return Boolean(residue && (residue.isAminoAcid || residue.isNucleic));
}

export function computeAtomStyles(
  packet: StructurePacket,
  context: ColoringContext,
  visibility: VisibilityOptions,
  representation: Representation,
): AtomStyle {
  const count = packet.structure.atoms;
  const positions = new Float32Array(count * 3);
  const radii = new Float32Array(count);
  const pickRadii = new Float32Array(count);
  const colors = new Float32Array(count * 3);
  const visible = new Uint8Array(count);

  const plan = representationPlan(representation);

  for (let i = 0; i < count; i += 1) {
    positions[i * 3] = packet.atoms.x[i];
    positions[i * 3 + 1] = packet.atoms.y[i];
    positions[i * 3 + 2] = packet.atoms.z[i];

    const [r, g, b] = atomColor(context, i);
    colors[i * 3] = r;
    colors[i * 3 + 1] = g;
    colors[i * 3 + 2] = b;

    if (!atomVisible(packet, i, visibility)) continue;
    visible[i] = 1;

    const vdw = packet.atoms.radius[i] || 1.5;
    const residueIndex = packet.atoms.residueIndex[i];
    let radius = 0;

    if (isPolymerResidue(packet, residueIndex)) {
      switch (plan.polymer) {
        case "none":
          radius = 0;
          break;
        case "vanDerWaals":
          radius = vdw;
          break;
        case "ball":
          radius = 0.3 * vdw;
          break;
        case "stick":
          radius = plan.bondRadius;
          break;
        case "tiny":
          radius = packet.atoms.isBackbone[i] ? 0.2 : 0;
          break;
      }
    } else {
      // Ligands, ions and (optionally) waters: always ball-and-stick.
      radius = 0.35 * vdw;
    }

    radii[i] = radius;
    pickRadii[i] = Math.max(radius, 0.55);
  }

  return { positions, radii, pickRadii, colors, visible };
}

export function computeBondPlan(
  packet: StructurePacket,
  representation: Representation,
  atomStyle: AtomStyle,
): BondPlan {
  const plan = representationPlan(representation);
  const { a, b } = packet.bonds;
  const keepA: number[] = [];
  const keepB: number[] = [];

  for (let i = 0; i < a.length; i += 1) {
    const ai = a[i];
    const bi = b[i];
    if (atomStyle.visible[ai] !== 1 || atomStyle.visible[bi] !== 1) continue;

    const polymerA = isPolymerResidue(packet, packet.atoms.residueIndex[ai]);
    const polymerB = isPolymerResidue(packet, packet.atoms.residueIndex[bi]);

    // In cartoon/backbone mode, polymer bonds are conveyed by the ribbon/trace,
    // so only small-molecule bonds are drawn.
    if ((representation === "cartoon" || representation === "backbone") && polymerA && polymerB) {
      continue;
    }

    keepA.push(ai);
    keepB.push(bi);
  }

  return {
    a: new Uint32Array(keepA),
    b: new Uint32Array(keepB),
    mode: plan.bonds,
    radius: plan.bondRadius,
  };
}
