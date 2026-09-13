export const SCHEMA = "mobile-media-probe-v1";
export const FRAME_SAMPLES = 1600;
export const FRAME_BYTES = 3200;
export const HEADER_BYTES = 12;
export const WIRE_BYTES = HEADER_BYTES + FRAME_BYTES;
export const MAX_PENDING_FRAMES = 120;

export function encodeFrame(epoch, sequence, pcm) {
  if (![epoch, sequence].every((value) => Number.isInteger(value) && value > 0 && value <= 0xffffffff)
      || !(pcm instanceof Int16Array) || pcm.length !== FRAME_SAMPLES) {
    throw new Error("invalid_pcm_frame");
  }
  const wire = new ArrayBuffer(WIRE_BYTES);
  const view = new DataView(wire);
  view.setUint32(0, 0x4d503031, false);
  view.setUint32(4, epoch, false);
  view.setUint32(8, sequence, false);
  for (let index = 0; index < pcm.length; index += 1) view.setInt16(HEADER_BYTES + index * 2, pcm[index], true);
  return wire;
}

export function decodeFrame(wire) {
  if (!(wire instanceof ArrayBuffer) || wire.byteLength !== WIRE_BYTES) throw new Error("invalid_wire_size");
  const view = new DataView(wire);
  if (view.getUint32(0, false) !== 0x4d503031) throw new Error("invalid_wire_magic");
  const epoch = view.getUint32(4, false), sequence = view.getUint32(8, false);
  if (!epoch || !sequence) throw new Error("invalid_wire_sequence");
  const pcm = new Float32Array(FRAME_SAMPLES);
  for (let index = 0; index < pcm.length; index += 1) pcm[index] = view.getInt16(HEADER_BYTES + index * 2, true) / 32768;
  return { epoch, sequence, pcm };
}

export function syntheticFrame(sequence, { silent = false } = {}) {
  const pcm = new Int16Array(FRAME_SAMPLES);
  if (silent) return pcm;
  const frequency = 440 + (sequence % 4) * 110;
  // Quiet, shaped tones; audio is generated locally and never saved by the probe.
  for (let index = 0; index < 640; index += 1) {
    const envelope = Math.sin(Math.PI * index / 640) ** 2;
    pcm[index] = Math.round(1000 * envelope * Math.sin(2 * Math.PI * frequency * index / 16000));
  }
  return pcm;
}

export function sampleStats(values) {
  if (!values.length) return { count: 0, p50: null, p95: null };
  const sorted = [...values].sort((a, b) => a - b), middle = Math.floor(sorted.length / 2);
  return {
    count: sorted.length,
    p50: sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2,
    p95: sorted[Math.max(0, Math.ceil(sorted.length * .95) - 1)],
  };
}

export function boundedMapSet(map, key, value, limit = MAX_PENDING_FRAMES) {
  if (map.size >= limit && !map.has(key)) map.delete(map.keys().next().value);
  map.set(key, value);
}

export function outputEstimate(context, renderedAudioTime, receivedAt) {
  if (typeof context.getOutputTimestamp !== "function") return null;
  try {
    const stamp = context.getOutputTimestamp();
    if (!Number.isFinite(stamp.contextTime) || !Number.isFinite(stamp.performanceTime) || stamp.performanceTime <= 0) return null;
    const estimate = stamp.performanceTime + (renderedAudioTime - stamp.contextTime) * 1000 - receivedAt;
    return Number.isFinite(estimate) && estimate >= -1000 && estimate <= 60000 ? estimate : null;
  } catch { return null; }
}
