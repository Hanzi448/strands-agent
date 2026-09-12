import { describe, expect, it } from "vitest";
import { base64ToInt16, floatToInt16, int16ToBase64, int16ToFloat32 } from "./pcm";

describe("floatToInt16", () => {
  it("clamps samples outside [-1, 1] instead of wrapping", () => {
    const pcm = floatToInt16(new Float32Array([-2, 0, 2]));
    expect(pcm).toEqual(new Int16Array([-32768, 0, 32767]));
  });

  it("scales positive and negative halves to the full Int16 range", () => {
    const pcm = floatToInt16(new Float32Array([0.5, -0.5]));
    // Int16 storage truncates, so the expected values are the truncated
    // products (16383.5 -> 16383).
    expect(pcm[0]).toBe(Math.trunc(0.5 * 0x7fff));
    expect(pcm[1]).toBe(Math.trunc(-0.5 * 0x8000));
  });
});

describe("int16ToFloat32", () => {
  it("round-trips through floatToInt16 for in-range floats", () => {
    const floats = new Float32Array([0, 0.25, -0.75]);
    const restored = int16ToFloat32(floatToInt16(floats));
    for (let i = 0; i < floats.length; i++) {
      expect(Math.abs(restored[i] - floats[i])).toBeLessThan(0.001);
    }
  });

  it("maps the Int16 extremes to exactly -1 and 1", () => {
    const restored = int16ToFloat32(new Int16Array([-32768, 32767]));
    expect(restored[0]).toBe(-1);
    expect(restored[1]).toBeGreaterThan(0.9999);
  });
});

describe("int16ToBase64 / base64ToInt16", () => {
  it("round-trips PCM samples through base64", () => {
    const pcm = new Int16Array([0, -1, 32767, -32768, 1234]);
    expect(base64ToInt16(int16ToBase64(pcm))).toEqual(pcm);
  });

  it("round-trips a buffer large enough to cross the 32 KiB chunk boundary", () => {
    // 40001 samples = 80002 bytes, straddling the 0x8000-byte chunking
    // inside int16ToBase64 -- this is the case the vendored sample's
    // single-spread version crashes on.
    const pcm = new Int16Array(40001);
    for (let i = 0; i < pcm.length; i++) pcm[i] = (i * 7) % 65536 - 32768;
    expect(base64ToInt16(int16ToBase64(pcm))).toEqual(pcm);
  });

  it("drops a trailing odd byte rather than misaligning the Int16 view", () => {
    // Three bytes: only the first two form a valid Int16 sample.
    const base64 = btoa(String.fromCharCode(0x01, 0x02, 0x03));
    expect(base64ToInt16(base64)).toEqual(new Int16Array([0x0201]));
  });
});
