/**
 * Conversions between the three audio representations the voice path
 * uses: Float32Array (Web Audio), Int16Array (16-bit PCM on the wire),
 * and base64 (inside the JSON WebSocket events).
 *
 * Adapted from the vendored reference sample
 * (`vendor/sample-nova-sonic-websocket-agentcore/frontend/src/websocket-presigned.ts`
 * and its hook), with two deliberate changes: base64 encoding is
 * chunked (the sample's single `String.fromCharCode(...bytes)` spread
 * overflows the call stack on real audio buffers), and decoding drops
 * a trailing odd byte instead of building a misaligned Int16 view.
 */

/** Float32 samples in [-1, 1] -> signed 16-bit PCM. */
export function floatToInt16(samples: Float32Array): Int16Array {
  const pcm = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return pcm;
}

/** Signed 16-bit PCM -> Float32 samples in [-1, 1]. */
export function int16ToFloat32(pcm: Int16Array): Float32Array {
  const floats = new Float32Array(pcm.length);
  for (let i = 0; i < pcm.length; i++) {
    floats[i] = pcm[i] / (pcm[i] < 0 ? 0x8000 : 0x7fff);
  }
  return floats;
}

// 32 KiB per String.fromCharCode call -- small enough that the spread
// argument never approaches the call-stack limit.
const BASE64_CHUNK = 0x8000;

/** Signed 16-bit PCM -> base64 (for `bidi_audio_input.audio`). */
export function int16ToBase64(pcm: Int16Array): string {
  const bytes = new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength);
  let binary = "";
  for (let i = 0; i < bytes.length; i += BASE64_CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(i, i + BASE64_CHUNK));
  }
  return btoa(binary);
}

/** base64 -> signed 16-bit PCM (for `bidi_audio_stream.audio`). */
export function base64ToInt16(base64: string): Int16Array {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  const usableBytes = bytes.length - (bytes.length % 2);
  return new Int16Array(bytes.buffer, 0, usableBytes / 2);
}
