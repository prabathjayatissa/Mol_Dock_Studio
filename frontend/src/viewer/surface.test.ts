import { describe, expect, it } from "vitest";

import { base64ToBytes, decodeFloat32, decodeUint32 } from "./surface";

function toBase64(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

describe("surface decoding", () => {
  it("round-trips float32 positions", () => {
    const values = new Float32Array([0, 1.5, -2.25, 3.75]);
    const decoded = decodeFloat32(toBase64(new Uint8Array(values.buffer)));
    expect(Array.from(decoded)).toEqual(Array.from(values));
  });

  it("round-trips uint32 indices", () => {
    const values = new Uint32Array([0, 1, 2, 100000]);
    const decoded = decodeUint32(toBase64(new Uint8Array(values.buffer)));
    expect(Array.from(decoded)).toEqual(Array.from(values));
  });

  it("decodes base64 to the exact bytes", () => {
    const bytes = new Uint8Array([1, 2, 3, 254, 255]);
    expect(Array.from(base64ToBytes(toBase64(bytes)))).toEqual(Array.from(bytes));
  });
});
