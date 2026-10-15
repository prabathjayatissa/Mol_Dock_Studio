/**
 * CPU ray–sphere atom picking.
 *
 * The viewer has no per-atom GPU ids, so picking is done analytically: cast a
 * ray from the camera through the cursor and take the nearest sphere it enters.
 * `positions` is a flat `[x,y,z,...]` array in structure space; `offset` is the
 * translation applied to the whole structure group, so the world centre of atom
 * `i` is `positions[3i..] + offset`.
 */

import * as THREE from "three";

export interface PickResult {
  index: number;
  distance: number;
}

/**
 * @param positions flat atom coordinates (structure space)
 * @param radii     pick radius per atom (world units)
 * @param visible   optional per-atom visibility mask
 * @param origin    ray origin in world space
 * @param direction normalised ray direction in world space
 * @param offset    structure-group translation
 */
export function pickAtom(
  positions: Float32Array | number[],
  radii: Float32Array | number[],
  visible: Uint8Array | null,
  origin: THREE.Vector3,
  direction: THREE.Vector3,
  offset: THREE.Vector3 = new THREE.Vector3(),
): PickResult | null {
  const count = Math.floor(positions.length / 3);
  let best: PickResult | null = null;
  const oc = new THREE.Vector3();

  for (let i = 0; i < count; i += 1) {
    if (visible && visible[i] === 0) continue;
    const radius = radii[i];
    if (radius <= 0) continue;

    oc.set(
      positions[i * 3] + offset.x - origin.x,
      positions[i * 3 + 1] + offset.y - origin.y,
      positions[i * 3 + 2] + offset.z - origin.z,
    );

    const b = oc.dot(direction);
    const c = oc.lengthSq() - radius * radius;
    const discriminant = b * b - c;
    if (discriminant < 0) continue;

    const sqrtD = Math.sqrt(discriminant);
    // `oc` is (centre - origin), so substituting into |P - C|^2 = r^2 gives
    // t^2 - 2*b*t + c = 0, whose roots are t = b ± sqrt(b^2 - c). Take the
    // nearest non-negative root (t < 0 means the sphere is behind the camera).
    let t = b - sqrtD;
    if (t < 0) t = b + sqrtD;
    if (t < 0) continue;

    if (best === null || t < best.distance) {
      best = { index: i, distance: t };
    }
  }
  return best;
}

/** Build a world-space ray from normalised device coordinates. */
export function rayFromNdc(
  camera: THREE.Camera,
  ndcX: number,
  ndcY: number,
): { origin: THREE.Vector3; direction: THREE.Vector3 } {
  const origin = new THREE.Vector3();
  const direction = new THREE.Vector3();
  const raycaster = new THREE.Raycaster();
  raycaster.setFromCamera(new THREE.Vector2(ndcX, ndcY), camera);
  origin.copy(raycaster.ray.origin);
  direction.copy(raycaster.ray.direction).normalize();
  return { origin, direction };
}
