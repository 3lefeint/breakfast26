// The overview of an X01 match summary drawn as a PNG: the legs won, the figures of all players side by side and
// the highlights. Drawn on a canvas instead of copied from the page so the picture does not depend on the glass
// and blur effects of the screen. `data` carries what the summary component shows: `summary`, `players` (with
// their `tint`), `legsWon`, `played`, `rows` ({ label, get, show, best, bar }), `isBest`, `barWidth`, `highlights`, and `crown` (the loaded crown image, optional).
import { cap, formatDateTime } from './util.js';
import crownUrl from './assets/crown.png';

const WIDTH = 1080, PAD = 48, SCALE = 2;

function token(name, fallback) {
  try {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
  } catch (e) {
    return fallback;
  }
}

function round(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
}

// Text that is shortened with an ellipsis when it does not fit in `max` pixels.
function fit(ctx, text, max) {
  const s = String(text);
  if (ctx.measureText(s).width <= max) return s;
  let cut = s;
  while (cut.length > 1 && ctx.measureText(cut + '…').width > max) cut = cut.slice(0, -1);
  return cut + '…';
}

export function drawSummary(data) {
  const { summary, players, legsWon, played, rows, isBest, barWidth, highlights, crown } = data;
  const bg = token('--bg', '#17171f'), text = token('--text', '#e8e8f0'), muted = token('--muted', '#85859e');
  const accent = token('--accent', '#8bc34a');
  const line = 'rgba(255, 255, 255, 0.14)', panel = 'rgba(255, 255, 255, 0.06)';
  const family = (() => {
    try { return getComputedStyle(document.body).fontFamily || 'system-ui, sans-serif'; } catch (e) { return 'system-ui, sans-serif'; }
  })();
  const font = (weight, size) => `${weight} ${size}px ${family}`;

  const inner = WIDTH - 2 * PAD;
  const labelW = 270;
  const cols = Math.max(1, players.length);
  const colW = (inner - 32 - labelW) / cols;
  const hlCols = Math.min(3, Math.max(1, highlights.length));
  const hlW = (inner - (hlCols - 1) * 16) / hlCols;
  const hlRows = Math.ceil(highlights.length / hlCols);

  // The height follows from the content: meta line, score band, table, highlights, footer.
  const headH = 68, rowH = 78;
  const tableH = headH + rows.length * rowH + 8;
  const height = PAD + 44 + 24 + 170 + 28 + tableH + 32 + hlRows * 136 + 24 + PAD / 2;

  const canvas = document.createElement('canvas');
  canvas.width = WIDTH * SCALE;
  canvas.height = height * SCALE;
  const ctx = canvas.getContext('2d');
  ctx.scale(SCALE, SCALE);
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, WIDTH, height);
  ctx.textBaseline = 'alphabetic';

  let y = PAD;
  // Meta line: the chips and the date with the duration.
  let x = PAD;
  for (const label of ['X01', String(summary.points_start)]) {
    ctx.font = font(700, 24);
    const w = ctx.measureText(label).width + 40;
    round(ctx, x, y, w, 44, 22);
    ctx.fillStyle = panel; ctx.fill(); ctx.strokeStyle = line; ctx.lineWidth = 1; ctx.stroke();
    ctx.fillStyle = text; ctx.fillText(label, x + 20, y + 30);
    x += w + 12;
  }
  const when = `${summary.started_at ? formatDateTime(summary.started_at) : ''}${played ? ` · ${played}` : ''}`;
  ctx.font = font(400, 24);
  ctx.fillStyle = muted;
  ctx.textAlign = 'right';
  ctx.fillText(fit(ctx, when, WIDTH - PAD - x - 8), WIDTH - PAD, y + 30);
  ctx.textAlign = 'left';
  y += 44 + 24;

  // Score band: one box per player with the legs won, the winner outlined.
  const gap = 12;
  const boxW = (inner - (cols - 1) * gap) / cols;
  players.forEach((p, i) => {
    const bx = PAD + i * (boxW + gap);
    const g = ctx.createLinearGradient(0, y, 0, y + 170);
    g.addColorStop(0, hexAlpha(p.tint, 0.5));
    g.addColorStop(1, hexAlpha(p.tint, 0.12));
    round(ctx, bx, y, boxW, 170, 22);
    ctx.fillStyle = g; ctx.fill();
    ctx.strokeStyle = p.name === summary.winner ? p.tint : line;
    ctx.lineWidth = p.name === summary.winner ? 3 : 1;
    ctx.stroke();
    ctx.textAlign = 'center';
    ctx.fillStyle = text;
    ctx.font = font(700, 32);
    const name = fit(ctx, cap(p.name), boxW - 24);
    ctx.fillText(name, bx + boxW / 2, y + 56);
    if (crown && p.name === summary.winner) {
      // Over the first letter like on the screen: 1.3 em wide, 0.6 em up and left of the name.
      const w = 1.3 * 32, left = bx + boxW / 2 - ctx.measureText(name).width / 2;
      ctx.save();
      ctx.shadowColor = 'rgba(0, 0, 0, 0.55)'; ctx.shadowBlur = 5; ctx.shadowOffsetY = 2;
      ctx.drawImage(crown, left - 0.6 * 32, y + 56 - 32 - 0.6 * 32, w, w * crown.naturalHeight / crown.naturalWidth);
      ctx.restore();
    }
    ctx.font = font(800, 76);
    ctx.fillText(String(legsWon[p.name] ?? 0), bx + boxW / 2, y + 140);
    ctx.textAlign = 'left';
  });
  y += 170 + 28;

  // The table: a heading row with the names, then one row per figure.
  round(ctx, PAD, y, inner, tableH, 22);
  ctx.fillStyle = panel; ctx.fill(); ctx.strokeStyle = line; ctx.lineWidth = 1; ctx.stroke();
  const colX = (i) => PAD + 16 + labelW + i * colW;
  ctx.font = font(700, 28);
  players.forEach((p, i) => {
    ctx.fillStyle = p.tint;
    ctx.fillText(fit(ctx, cap(p.name), colW - 16), colX(i), y + 46);
  });
  rows.forEach((row, r) => {
    const ry = y + headH + r * rowH;
    ctx.strokeStyle = line; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(PAD + 16, ry); ctx.lineTo(PAD + inner - 16, ry); ctx.stroke();
    ctx.font = font(400, 26);
    ctx.fillStyle = muted;
    ctx.fillText(fit(ctx, row.label, labelW - 12), PAD + 16, ry + 42);
    players.forEach((p, i) => {
      ctx.font = font(700, 32);
      ctx.fillStyle = isBest(row, p) ? accent : text;
      ctx.fillText(fit(ctx, String(row.show(p)), colW - 16), colX(i), ry + 42);
      if (row.bar) {
        const bw = colW - 24;
        round(ctx, colX(i), ry + 54, bw, 6, 3);
        ctx.fillStyle = line; ctx.fill();
        const w = Math.max(0, bw * barWidth(row, p) / 100);
        if (w > 0) { round(ctx, colX(i), ry + 54, w, 6, 3); ctx.fillStyle = p.tint; ctx.fill(); }
      }
    });
  });
  y += tableH + 32;

  // The highlights.
  highlights.forEach((h, i) => {
    const hx = PAD + (i % hlCols) * (hlW + 16), hy = y + Math.floor(i / hlCols) * 136;
    round(ctx, hx, hy, hlW, 120, 18);
    ctx.fillStyle = panel; ctx.fill(); ctx.strokeStyle = line; ctx.lineWidth = 1; ctx.stroke();
    ctx.font = font(400, 22); ctx.fillStyle = muted;
    ctx.fillText(fit(ctx, h.label, hlW - 32), hx + 16, hy + 30);
    ctx.font = font(700, 36); ctx.fillStyle = text;
    const value = `${h.value}${h.unit ? ' ' + h.unit : ''}`;
    ctx.fillText(value, hx + 16, hy + 70);
    ctx.font = font(400, 22); ctx.fillStyle = muted;
    ctx.fillText(fit(ctx, h.names.map(cap).join(', '), hlW - 32), hx + 16, hy + 104);
  });

  ctx.font = font(600, 22);
  ctx.fillStyle = muted;
  ctx.textAlign = 'right';
  ctx.fillText('Breakfast', WIDTH - PAD, height - PAD / 2 - 6);
  return canvas;
}

// '#rrggbb' as an rgba() with the given opacity; any other color notation is returned as it is.
function hexAlpha(color, alpha) {
  const m = /^#([0-9a-f]{6})$/i.exec(color);
  if (!m) return color;
  const n = parseInt(m[1], 16);
  return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

// Saves the picture through the share dialog where the browser can share files, else as a download.
export async function saveSummaryImage(data) {
  const crown = await new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);       // the picture is fine without the crown
    img.src = crownUrl;
  });
  const canvas = drawSummary({ ...data, crown });
  const blob = await new Promise((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('toBlob'))), 'image/png'));
  const name = `x01-${(data.summary.started_at || '').slice(0, 10) || 'match'}.png`;
  const file = new File([blob], name, { type: 'image/png' });
  if (navigator.canShare?.({ files: [file] })) {
    try {
      await navigator.share({ files: [file] });
      return;
    } catch (e) {
      if (e?.name === 'AbortError') return;       // closed without choosing: nothing to save
    }
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}
