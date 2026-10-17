// The board model in the browser: the same geometry as breakfast/detection/geometry.py, enough to draw the rings and wires over a
// camera picture while the four reference points are dragged. Board coordinates: millimetres from the center, x to the right, y up;
// the wire between 20 and 1 lies 9 degrees clockwise from the top.
export const R_OUT = 170;
export const ANGLES = [9, 99, 189, 279];                   // wires 20|1, 6|10, 3|19, 11|14 on the outer edge of the double ring
export const WIRE_NAMES = ['20 | 1', '6 | 10', '3 | 19', '11 | 14'];
export const RING_R = [170, 162, 107, 99, 15.9, 6.35];

const rad = (d) => (d * Math.PI) / 180;
export const boardPt = (r, deg) => [r * Math.sin(rad(deg)), r * Math.cos(rad(deg))];

// Homography (3x3, row by row) that takes four board points to four pixels: the eight unknowns of the direct linear transform.
export function homography(src, dst) {
  const A = [];
  const b = [];
  for (let i = 0; i < 4; i++) {
    const [x, y] = src[i];
    const [u, v] = dst[i];
    A.push([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.push(u);
    A.push([0, 0, 0, x, y, 1, -v * x, -v * y]); b.push(v);
  }
  for (let c = 0; c < 8; c++) {                              // Gaussian elimination with pivoting
    let p = c;
    for (let r = c + 1; r < 8; r++) if (Math.abs(A[r][c]) > Math.abs(A[p][c])) p = r;
    [A[c], A[p]] = [A[p], A[c]]; [b[c], b[p]] = [b[p], b[c]];
    for (let r = c + 1; r < 8; r++) {
      const f = A[r][c] / A[c][c];
      for (let k = c; k < 8; k++) A[r][k] -= f * A[c][k];
      b[r] -= f * b[c];
    }
  }
  const h = new Array(8);
  for (let r = 7; r >= 0; r--) {
    let s = b[r];
    for (let k = r + 1; k < 8; k++) s -= A[r][k] * h[k];
    h[r] = s / A[r][r];
  }
  return [...h, 1];
}

export function project(H, x, y) {
  const w = H[6] * x + H[7] * y + H[8];
  return [(H[0] * x + H[1] * y + H[2]) / w, (H[3] * x + H[4] * y + H[5]) / w];
}

// The model of one camera from its four reference points (pixels).
export function modelFor(ref) {
  return homography(ANGLES.map((a) => boardPt(R_OUT, a)), ref);
}

// the worker sends the radii with keys like "99.0" (floats), the ring list here has plain numbers
const radiusOf = (radii, r) => radii?.[String(r)] ?? radii?.[`${r}.0`] ?? r;

export function ringPath(H, r, radii, steps = 120) {
  const rr = radiusOf(radii, r);
  let d = '';
  for (let i = 0; i < steps; i++) {
    const [x, y] = project(H, ...boardPt(rr, (360 * i) / steps));
    d += `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)} `;
  }
  return d + 'Z';
}

export function wirePath(H, deg, radii) {
  const [x0, y0] = project(H, ...boardPt(15.9, deg));
  const [x1, y1] = project(H, ...boardPt(radiusOf(radii, 170), deg));
  return `M${x0.toFixed(1)} ${y0.toFixed(1)} L${x1.toFixed(1)} ${y1.toFixed(1)}`;
}
