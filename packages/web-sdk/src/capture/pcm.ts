// Float [-1, 1] to PCM16: clamp, then round(s < 0 ? s * 32768 : s * 32767).
export function floatToPcm16(x: Float32Array): Int16Array {
  const out = new Int16Array(x.length);
  for (let i = 0; i < x.length; i++) {
    const s = Math.max(-1, Math.min(1, x[i]!));
    out[i] = Math.round(s < 0 ? s * 32768 : s * 32767);
  }
  return out;
}
