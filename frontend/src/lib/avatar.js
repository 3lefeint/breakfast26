// A small deterministic "avatar" for a player: the same name always gives the same picture. A hash of
// the name seeds a random generator that decides the look of a little dartboard (rotation, colors,
// which segments are lit, the bull).

// FNV-1a, 32 bit.
export function hashName(name) {
  let h = 0x811c9dc5;
  for (const ch of String(name).toLowerCase()) {
    h ^= ch.codePointAt(0);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}

// A seeded generator (mulberry32): a function that returns numbers from 0 up to 1.
export function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// The hue (0-360) of a #rrggbb color, null for anything else.
export function hueOf(hex) {
  if (!/^#[0-9a-f]{6}$/i.test(hex || '')) return null;
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  if (d === 0) return 0;
  let h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  h *= 60;
  return h < 0 ? h + 360 : h;
}

const hsl = (h, s, l) => `hsl(${Math.round(((h % 360) + 360) % 360)} ${s}% ${l}%)`;

// What an avatar looks like: the description the component draws. `color` is the color the player
// picked in the profile (the picture is drawn in its hue), without one the hue comes from the hash.
export function avatarSpec(name, color = null) {
  const random = rng(hashName(name));
  const hue = hueOf(color) ?? random() * 360;
  random();                                   // keeps the rest the same whether or not there is a color
  const rotation = Math.floor(random() * 18);
  const ringShift = [150, 180, 210, 40, -40][Math.floor(random() * 5)];
  const lit = new Set();
  const litCount = 3 + Math.floor(random() * 4);
  while (lit.size < litCount) lit.add(Math.floor(random() * 20));
  const bull = random() < 0.5;
  const segments = Array.from({ length: 20 }, (_, i) => ({
    dark: i % 2 === 0, lit: lit.has(i),
    fill: lit.has(i) ? hsl(hue, 75, 58) : i % 2 === 0 ? hsl(hue, 45, 18) : hsl(hue, 38, 30),
    ring: i % 2 === 0 ? hsl(hue + ringShift, 62, 46) : hsl(hue + ringShift + 25, 55, 36),
  }));
  return {
    rotation, segments,
    bull: bull ? hsl(hue + ringShift, 70, 52) : hsl(hue, 80, 65),
    outerBull: bull ? hsl(hue, 60, 40) : hsl(hue + ringShift, 55, 38),
    edge: hsl(hue, 55, 62),
  };
}
