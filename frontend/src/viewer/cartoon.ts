/**
 * Schematic cartoon ribbon.
 *
 * This is an original, honest approximation: a flat ribbon swept along a
 * Catmull–Rom spline through each chain's Cα trace, coloured by residue. It is
 * **not** a DSSP/MolScript-accurate cartoon with helix coils and sheet arrows;
 * that refinement is listed as pending in the roadmap. It is fast, robust to
 * missing backbone atoms, and good enough to read the fold.
 */

import * as THREE from "three";

import type { PacketResidue, StructurePacket } from "../api/types";
import type { RGB } from "./coloring";

export interface RibbonGeometry {
  positions: Float32Array;
  normals: Float32Array;
  colors: Float32Array;
  indices: Uint32Array;
}

const SAMPLES_PER_RESIDUE = 6;

function caPosition(packet: StructurePacket, atomIndex: number): THREE.Vector3 {
  return new THREE.Vector3(
    packet.atoms.x[atomIndex],
    packet.atoms.y[atomIndex],
    packet.atoms.z[atomIndex],
  );
}

export function buildCartoon(
  packet: StructurePacket,
  colorFor: (residueIndex: number) => RGB,
  width = 1.5,
): RibbonGeometry | null {
  // Group amino-acid residues that have a Cα by chain, preserving order.
  const byChain = new Map<number, PacketResidue[]>();
  for (const residue of packet.residues) {
    if (!residue.isAminoAcid || residue.caIndex === null) continue;
    const list = byChain.get(residue.chainIndex) ?? [];
    list.push(residue);
    byChain.set(residue.chainIndex, list);
  }

  const positions: number[] = [];
  const normals: number[] = [];
  const colors: number[] = [];
  const indices: number[] = [];
  const half = width / 2;

  for (const residues of byChain.values()) {
    if (residues.length < 2) continue;

    const points = residues.map((residue) => caPosition(packet, residue.caIndex as number));
    const curve = new THREE.CatmullRomCurve3(points, false, "catmullrom", 0.5);
    const reference: THREE.Vector3[] = residues.map((residue) => {
      if (residue.cIndex !== null) {
        const c = caPosition(packet, residue.cIndex);
        return c.sub(caPosition(packet, residue.caIndex as number)).normalize();
      }
      return new THREE.Vector3(0, 1, 0);
    });

    const sampleCount = (residues.length - 1) * SAMPLES_PER_RESIDUE + 1;
    const baseVertex = positions.length / 3;

    for (let s = 0; s < sampleCount; s += 1) {
      const t = sampleCount === 1 ? 0 : s / (sampleCount - 1);
      const point = curve.getPoint(t);
      const tangent = curve.getTangent(t).normalize();

      const residueIndex = Math.min(
        residues.length - 1,
        Math.max(0, Math.round(t * (residues.length - 1))),
      );
      const residue = residues[residueIndex];
      let ref = reference[residueIndex];
      if (Math.abs(ref.dot(tangent)) > 0.95) ref = new THREE.Vector3(0, 1, 0);

      const side = new THREE.Vector3().crossVectors(tangent, ref);
      if (side.lengthSq() < 1e-8) side.crossVectors(tangent, new THREE.Vector3(0, 0, 1));
      side.normalize();
      const faceNormal = new THREE.Vector3().crossVectors(side, tangent).normalize();

      const left = point.clone().addScaledVector(side, half);
      const right = point.clone().addScaledVector(side, -half);

      positions.push(left.x, left.y, left.z, right.x, right.y, right.z);
      normals.push(
        faceNormal.x, faceNormal.y, faceNormal.z,
        faceNormal.x, faceNormal.y, faceNormal.z,
      );
      const [r, g, b] = colorFor(residue.index);
      colors.push(r, g, b, r, g, b);
    }

    for (let s = 0; s < sampleCount - 1; s += 1) {
      const a = baseVertex + s * 2;
      const b = a + 1;
      const c = a + 2;
      const d = a + 3;
      indices.push(a, b, c, b, d, c);
    }
  }

  if (positions.length === 0) return null;
  return {
    positions: new Float32Array(positions),
    normals: new Float32Array(normals),
    colors: new Float32Array(colors),
    indices: new Uint32Array(indices),
  };
}
