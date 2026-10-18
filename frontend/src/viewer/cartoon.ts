/**
 * Schematic cartoon ribbon.
 *
 * A tube swept along a Catmull–Rom spline through each chain's Cα trace,
 * coloured by residue. Tube segments give a smooth, PyMOL-like cartoon with
 * proper per-vertex normals for lighting, instead of the previous flat ribbon.
 *
 * This is an original, honest approximation: it is **not** a DSSP/MolScript
 * accurate cartoon with helix coils and sheet arrows; that refinement is
 * listed as pending in the roadmap. It is fast, robust to missing backbone
 * atoms, and good enough to read the fold.
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

const TUBE_RADIUS_SEGMENTS = 8;    // around the tube cross-section
const TUBE_RADIUS = 0.45;          // tube radius in Å
const SAMPLES_PER_RESIDUE = 12;    // along the spline; higher = smoother

function caPosition(packet: StructurePacket, atomIndex: number): THREE.Vector3 {
  return new THREE.Vector3(
    packet.atoms.x[atomIndex],
    packet.atoms.y[atomIndex],
    packet.atoms.z[atomIndex],
  );
}

function buildTubeSegment(
  positions: number[],
  normals: number[],
  colors: number[],
  indices: number[],
  point: THREE.Vector3,
  normal: THREE.Vector3,
  binormal: THREE.Vector3,
  color: RGB,
  prevBase: number | null,
) {
  // Ring vertices around the cross-section at this spline sample.
  const ringStart = positions.length / 3;
  for (let s = 0; s < TUBE_RADIUS_SEGMENTS; s += 1) {
    const theta = (s / TUBE_RADIUS_SEGMENTS) * Math.PI * 2;
    const offset = new THREE.Vector3()
      .addScaledVector(normal, Math.cos(theta) * TUBE_RADIUS)
      .addScaledVector(binormal, Math.sin(theta) * TUBE_RADIUS);
    const vertex = point.clone().add(offset);
    positions.push(vertex.x, vertex.y, vertex.z);
    normals.push(offset.x, offset.y, offset.z);
    const [r, g, b] = color;
    colors.push(r, g, b);
  }

  // Quads between this ring and the previous ring.
  if (prevBase !== null) {
    for (let s = 0; s < TUBE_RADIUS_SEGMENTS; s += 1) {
      const sNext = (s + 1) % TUBE_RADIUS_SEGMENTS;
      const a = prevBase + s;
      const b = prevBase + sNext;
      const c = ringStart + sNext;
      const d = ringStart + s;
      indices.push(a, b, c, b, d, c);
    }
  }

  return ringStart;
}

export function buildCartoon(
  packet: StructurePacket,
  colorFor: (residueIndex: number) => RGB,
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
    let prevRing: number | null = null;

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

      const normal = new THREE.Vector3().crossVectors(tangent, ref);
      if (normal.lengthSq() < 1e-8) normal.crossVectors(tangent, new THREE.Vector3(0, 0, 1));
      normal.normalize();
      const binormal = new THREE.Vector3().crossVectors(tangent, normal);

      const color = colorFor(residue.index);
      prevRing = buildTubeSegment(
        positions, normals, colors, indices,
        point, normal, binormal, color,
        prevRing,
      );
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
