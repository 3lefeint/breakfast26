<script>
  import { t } from '../../../lib/i18n.js';
  // Where the darts landed: every dart as a glowing point on the board and, from
  // DENSITY_MIN darts on, a density overlay that shows where they cluster.
  import { SEGMENT_ORDER, RINGS_MM, polar } from '../../../lib/dartboard.js';

  let { darts = [], corrected = 0 } = $props();

  const DENSITY_MIN = 30;
  const HALF = 192, BOARD_R = 150;                  // board units -> px; the numbers reach out to about 185
  const K = BOARD_R / RINGS_MM.DOUBLE_OUT;
  const LABEL_R = RINGS_MM.DOUBLE_OUT + 32;
  const RINGS = [RINGS_MM.BULL, RINGS_MM.OUTER_BULL, RINGS_MM.TRIPLE_IN, RINGS_MM.TRIPLE_OUT, RINGS_MM.DOUBLE_IN, RINGS_MM.DOUBLE_OUT];

  // Density: a Gaussian blob per dart on a grid over the square around the board.
  const CELLS = 72, SPAN = 1.2, SIGMA = 0.055;       // board units
  const CELL = (2 * SPAN) / CELLS;

  let density = $derived.by(() => {
    if (darts.length < DENSITY_MIN) return [];
    const grid = new Float32Array(CELLS * CELLS);
    const reach = Math.ceil((3 * SIGMA) / CELL);
    for (const d of darts) {
      const cx = (d.x + SPAN) / CELL, cy = (SPAN - d.y) / CELL;
      for (let j = Math.max(0, Math.floor(cy) - reach); j <= Math.min(CELLS - 1, Math.floor(cy) + reach); j++) {
        for (let i = Math.max(0, Math.floor(cx) - reach); i <= Math.min(CELLS - 1, Math.floor(cx) + reach); i++) {
          const dx = (i + 0.5 - cx) * CELL, dy = (j + 0.5 - cy) * CELL;
          grid[j * CELLS + i] += Math.exp(-(dx * dx + dy * dy) / (2 * SIGMA * SIGMA));
        }
      }
    }
    const max = Math.max(...grid);
    const cells = [];
    for (let j = 0; j < CELLS; j++) {
      for (let i = 0; i < CELLS; i++) {
        const v = grid[j * CELLS + i] / max;
        if (v < 0.05) continue;
        cells.push({ x: (i * CELL - SPAN) * BOARD_R, y: (j * CELL - SPAN) * BOARD_R, o: Math.sqrt(v) * 0.8 });
      }
    }
    return cells;
  });

  const px = (x) => x * BOARD_R;
  const py = (y) => -y * BOARD_R;
  let spokes = $derived(SEGMENT_ORDER.map((n, i) => ({ n, i, a: polar(RINGS_MM.OUTER_BULL, i * 18 + 9, K), b: polar(RINGS_MM.DOUBLE_OUT, i * 18 + 9, K), label: polar(LABEL_R, i * 18, K) })));
</script>

{#if !darts.length}
  <div class="empty">{t('No dart positions recorded yet.')}</div>
{:else}
  <div class="wrap">
    <svg viewBox="{-HALF} {-HALF} {2 * HALF} {2 * HALF}" class="board" role="img"
         aria-label={t('Dartboard with the positions of the darts')}>
      <defs>
        <filter id="dart-glow" x="-200%" y="-200%" width="500%" height="500%">
          <feGaussianBlur stdDeviation="2.2" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
        <filter id="density-blur" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="4.5" /></filter>
        <clipPath id="board-clip"><circle r={RINGS_MM.DOUBLE_OUT * K + 14} /></clipPath>
      </defs>
      <circle r={RINGS_MM.DOUBLE_OUT * K} class="disc" />
      {#each RINGS as r}<circle r={r * K} class="wire" />{/each}
      {#each spokes as s}
        <line x1={s.a[0]} y1={s.a[1]} x2={s.b[0]} y2={s.b[1]} class="wire" />
        <text class="num" x={s.label[0]} y={s.label[1]}>{s.n}</text>
      {/each}
      <g clip-path="url(#board-clip)">
        <g filter="url(#density-blur)">
          {#each density as c}<rect x={c.x} y={c.y} width={CELL * BOARD_R + 0.4} height={CELL * BOARD_R + 0.4} class="density" opacity={c.o} />{/each}
        </g>
      </g>
      <g filter="url(#dart-glow)">
        {#each darts as d}
          <circle cx={px(d.x)} cy={py(d.y)} r="2.4" class="dart" opacity={density.length ? 0.55 : 0.9}>
            <title>{d.field ?? ''}</title>
          </circle>
        {/each}
      </g>
    </svg>
  </div>
  <div class="note">
    {t('{n} darts with a position', { n: darts.length })}{#if corrected} · {t('{n} corrected darts are left out', { n: corrected })}{/if}
  </div>
{/if}

<style>
  .empty { color: var(--muted); text-align: center; padding: 1.5rem 0; font-size: 0.8rem; }
  .wrap { display: flex; justify-content: center; }
  .board { width: 100%; max-width: 32rem; height: auto; }
  .disc { fill: var(--surface); stroke: var(--border); stroke-width: 1; }
  .wire { fill: none; stroke: var(--border); stroke-width: 0.8; }
  .num { fill: var(--muted); font-size: 13px; font-weight: 600; text-anchor: middle; dominant-baseline: central; pointer-events: none; }
  .density { fill: var(--accent); pointer-events: none; }
  .dart { fill: var(--accent); }
  .note { font-size: 0.7rem; color: var(--muted); text-align: center; margin-top: 0.4rem; }
</style>
