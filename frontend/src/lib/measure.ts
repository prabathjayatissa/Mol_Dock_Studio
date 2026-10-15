/**
 * Measurement geometry over a structure packet.
 *
 * Pure and synchronous so the UI can compute a distance/angle the moment the
 * user finishes a selection, without a round-trip to the backend.
 */

import type { StructurePacket } from "../api/types";

export type Vec3 = [number, number, number];

export function atomPosition(packet: StructurePacket, index: number): Vec3 {
  return [packet.atoms.x[index], packet.atoms.y[index], packet.atoms.z[index]];
}

export function distanceBetween(packet: StructurePacket, i: number, j: number): number {
  const a = atomPosition(packet, i);
  const b = atomPosition(packet, j);
  return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}

/** Angle in degrees at vertex `j`, between bonds j→i and j→k. */
export function angleBetween(packet: StructurePacket, i: number, j: number, k: number): number {
  const a = atomPosition(packet, i);
  const b = atomPosition(packet, j);
  const c = atomPosition(packet, k);
  const u: Vec3 = [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const v: Vec3 = [c[0] - b[0], c[1] - b[1], c[2] - b[2]];
  const dot = u[0] * v[0] + u[1] * v[1] + u[2] * v[2];
  const nu = Math.hypot(u[0], u[1], u[2]);
  const nv = Math.hypot(v[0], v[1], v[2]);
  if (nu === 0 || nv === 0) return 0;
  const cosine = Math.max(-1, Math.min(1, dot / (nu * nv)));
  return (Math.acos(cosine) * 180) / Math.PI;
}

/** Short human label for an atom, e.g. `ALA42.CA` or `BEN1.C7`. */
export function atomLabel(packet: StructurePacket, index: number): string {
  const residueIndex = packet.atoms.residueIndex[index];
  const residue = packet.residues[residueIndex];
  const name = packet.atoms.name[index] ?? "?";
  if (!residue) return name;
  const chain = residue.chainId && residue.chainId !== " " ? `${residue.chainId} ` : "";
  return `${chain}${residue.name}${residue.seq}${residue.insertionCode || ""}.${name}`;
}
