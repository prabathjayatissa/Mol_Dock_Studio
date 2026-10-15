/**
 * Decoding and building of server-computed molecular surfaces.
 *
 * The backend sends base64-encoded, little-endian float32 positions/normals and
 * uint32 triangle indices (see `docs/architecture.md`). Decoding is done with
 * typed arrays so a 100k-triangle mesh never becomes one JS object per vertex.
 */

import * as THREE from "three";

import type { SurfacePayload } from "../api/types";

export function base64ToBytes(base64: string): Uint8Array {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

export function decodeFloat32(base64: string): Float32Array {
  const bytes = base64ToBytes(base64);
  // Copy into an aligned buffer: the base64 decode is byte-aligned, not 4-byte.
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  return new Float32Array(copy.buffer);
}

export function decodeUint32(base64: string): Uint32Array {
  const bytes = base64ToBytes(base64);
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  return new Uint32Array(copy.buffer);
}

export interface DecodedSurface {
  positions: Float32Array;
  normals: Float32Array;
  indices: Uint32Array;
}

export function decodeSurface(payload: SurfacePayload): DecodedSurface {
  if (payload.encoding !== "base64") {
    throw new Error(`Unsupported surface encoding '${payload.encoding}'.`);
  }
  const positions = decodeFloat32(payload.positions);
  const indices = decodeUint32(payload.indices);
  const normals = payload.normals
    ? decodeFloat32(payload.normals)
    : new Float32Array(positions.length);
  return { positions, normals, indices };
}

export function buildSurfaceGeometry(payload: SurfacePayload): THREE.BufferGeometry {
  const { positions, normals, indices } = decodeSurface(payload);
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  if (normals.length === positions.length) {
    geometry.setAttribute("normal", new THREE.BufferAttribute(normals, 3));
  }
  geometry.setIndex(new THREE.BufferAttribute(indices, 1));
  if (normals.length !== positions.length) geometry.computeVertexNormals();
  geometry.computeBoundingSphere();
  return geometry;
}
