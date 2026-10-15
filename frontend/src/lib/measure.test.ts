import { describe, expect, it } from "vitest";

import type { StructurePacket } from "../api/types";
import { angleBetween, atomLabel, distanceBetween } from "./measure";

function packetWith(points: [number, number, number][]): StructurePacket {
  return {
    atoms: {
      x: points.map((p) => p[0]),
      y: points.map((p) => p[1]),
      z: points.map((p) => p[2]),
      name: points.map((_, i) => `A${i}`),
      residueIndex: points.map(() => 0),
    },
    residues: [
      { index: 0, name: "ALA", seq: 1, chainId: "A", insertionCode: "", label: "ALA1" },
    ],
  } as unknown as StructurePacket;
}

describe("measure", () => {
  it("computes a distance", () => {
    const packet = packetWith([
      [0, 0, 0],
      [0, 3, 4],
    ]);
    expect(distanceBetween(packet, 0, 1)).toBeCloseTo(5, 6);
  });

  it("computes a right angle", () => {
    const packet = packetWith([
      [1, 0, 0],
      [0, 0, 0],
      [0, 1, 0],
    ]);
    expect(angleBetween(packet, 0, 1, 2)).toBeCloseTo(90, 6);
  });

  it("computes a straight angle", () => {
    const packet = packetWith([
      [1, 0, 0],
      [0, 0, 0],
      [-1, 0, 0],
    ]);
    expect(angleBetween(packet, 0, 1, 2)).toBeCloseTo(180, 6);
  });

  it("labels an atom with chain, residue and atom name", () => {
    const packet = packetWith([[0, 0, 0]]);
    expect(atomLabel(packet, 0)).toBe("A ALA1.A0");
  });
});
