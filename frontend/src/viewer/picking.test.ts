import { describe, expect, it } from "vitest";
import * as THREE from "three";

import { pickAtom } from "./picking";

describe("pickAtom", () => {
  // Two atoms on the x-axis at x=0 and x=10, radius 1.
  const positions = new Float32Array([0, 0, 0, 10, 0, 0]);
  const radii = new Float32Array([1, 1]);

  it("hits the nearest intersect along the ray", () => {
    const origin = new THREE.Vector3(0, 0, -20);
    const direction = new THREE.Vector3(0, 0, 1);
    const hit = pickAtom(positions, radii, null, origin, direction);
    expect(hit?.index).toBe(0);
  });

  it("prefers the closer atom when both are on the ray", () => {
    const origin = new THREE.Vector3(-20, 0, 0);
    const direction = new THREE.Vector3(1, 0, 0);
    const hit = pickAtom(positions, radii, null, origin, direction);
    expect(hit?.index).toBe(0);
  });

  it("returns null when the ray misses every sphere", () => {
    const origin = new THREE.Vector3(0, 50, -20);
    const direction = new THREE.Vector3(0, 0, 1);
    expect(pickAtom(positions, radii, null, origin, direction)).toBeNull();
  });

  it("respects the group offset", () => {
    const origin = new THREE.Vector3(0, 0, -20);
    const direction = new THREE.Vector3(0, 0, 1);
    // Translate the whole group by -10 on x so atom 1 (at x=10) lands on the ray
    // and atom 0 (at x=0) moves off it.
    const offset = new THREE.Vector3(-10, 0, 0);
    const hit = pickAtom(positions, radii, null, origin, direction, offset);
    expect(hit?.index).toBe(1);
  });

  it("skips atoms masked as invisible", () => {
    const origin = new THREE.Vector3(0, 0, -20);
    const direction = new THREE.Vector3(0, 0, 1);
    const visible = new Uint8Array([0, 1]);
    const hit = pickAtom(positions, radii, visible, origin, direction);
    expect(hit).toBeNull();
  });
});
