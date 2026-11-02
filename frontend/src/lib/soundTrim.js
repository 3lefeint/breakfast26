// Proposes where to cut a sound: the first and the last point above a threshold, with a little room on both sides,
// and short fades. Only a proposal; the editor lets the user change every value afterwards.

export const TRIM_THRESHOLD_DB = -40;
export const TRIM_ROOM_BEFORE = 0.02;    // seconds kept before the first sound
export const TRIM_ROOM_AFTER = 0.08;     // seconds kept after the last sound
export const TRIM_FADE_IN = 0.015;
export const TRIM_FADE_OUT = 0.08;
const WINDOW_SECONDS = 0.005;            // a single sample above the threshold is not a sound, a 5 ms stretch with one is

// channels: an array of Float32Array (one per channel), sampleRate in Hz.
// Returns { start, end, fadeIn, fadeOut } in seconds, or null when nothing in the sound reaches the threshold.
export function proposeTrim(channels, sampleRate, thresholdDb = TRIM_THRESHOLD_DB) {
  if (!channels.length || !sampleRate) return null;
  const length = channels[0].length;
  const duration = length / sampleRate;
  const limit = 10 ** (thresholdDb / 20);
  const size = Math.max(1, Math.round(sampleRate * WINDOW_SECONDS));
  const loud = (from) => {
    const to = Math.min(length, from + size);
    for (const data of channels) for (let i = from; i < to; i++) if (Math.abs(data[i]) > limit) return true;
    return false;
  };
  let first = -1, last = -1;
  for (let from = 0; from < length; from += size) {
    if (loud(from)) {
      if (first < 0) first = from;
      last = Math.min(length, from + size);
    }
  }
  if (first < 0) return null;
  const start = Math.max(0, first / sampleRate - TRIM_ROOM_BEFORE);
  const end = Math.min(duration, last / sampleRate + TRIM_ROOM_AFTER);
  const span = end - start;
  const fadeIn = Math.min(TRIM_FADE_IN, span / 2);
  const fadeOut = Math.min(TRIM_FADE_OUT, span - fadeIn);
  return { start, end, fadeIn, fadeOut };
}
