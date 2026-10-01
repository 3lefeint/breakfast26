// Standard dartboard geometry, in millimetres from the center.
const BULL = 6.35;
const OUTER_BULL = 15.9;
const TRIPLE_IN = 99;
const TRIPLE_OUT = 107;
const DOUBLE_IN = 162;
const DOUBLE_OUT = 170;

// Clockwise from the top.
export const SEGMENT_ORDER = [20, 1, 18, 4, 13, 6, 10, 15, 2, 17, 3, 19, 7, 16, 8, 11, 14, 9, 12, 5];

export const RINGS_MM = { BULL, OUTER_BULL, TRIPLE_IN, TRIPLE_OUT, DOUBLE_IN, DOUBLE_OUT };

// Field name the correction endpoints understand (`S20`, `D16`, `T19`, `25`,
// `50`, `0`) for a point given in mm from the center, x to the right and y
// down. A point exactly on a ring wire counts for the inner ring.
export function fieldAtMm(x, y) {
  const r = Math.hypot(x, y);
  if (r <= BULL) return '50';
  if (r <= OUTER_BULL) return '25';
  if (r > DOUBLE_OUT) return '0';

  const degrees = (Math.atan2(x, -y) * 180) / Math.PI; // 0 at the top, clockwise
  const index = Math.floor((((degrees + 9) % 360) + 360) % 360 / 18);
  const n = SEGMENT_ORDER[index];

  if (r <= TRIPLE_IN) return `S${n}`;
  if (r <= TRIPLE_OUT) return `T${n}`;
  if (r <= DOUBLE_IN) return `S${n}`;
  return `D${n}`;
}

// A point at `rMm` from the center and `deg` clockwise from the top, drawn
// `scale` units per millimetre (y down, as in SVG).
export function polar(rMm, deg, scale) {
  const a = (deg * Math.PI) / 180;
  return [rMm * scale * Math.sin(a), -rMm * scale * Math.cos(a)];
}

// The ring segment between two radii and two angles, as an SVG path.
export function bandPath(rInMm, rOutMm, deg0, deg1, scale) {
  const [x0, y0] = polar(rOutMm, deg0, scale);
  const [x1, y1] = polar(rOutMm, deg1, scale);
  const [x2, y2] = polar(rInMm, deg1, scale);
  const [x3, y3] = polar(rInMm, deg0, scale);
  const rOut = rOutMm * scale, rIn = rInMm * scale;
  return `M${x0},${y0} A${rOut},${rOut} 0 0 1 ${x1},${y1} L${x2},${y2} A${rIn},${rIn} 0 0 0 ${x3},${y3} Z`;
}
