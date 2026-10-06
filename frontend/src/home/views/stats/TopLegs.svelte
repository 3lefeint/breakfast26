<script>
  import { t } from '../../../lib/i18n.js';
  // The fastest legs won, best first: one bar per leg, its length is the darts
  // thrown on an axis from 0 and printed inside it, with the 3-dart average of
  // that leg on the right. The date is in the hover.
  let { legs = [] } = $props();

  const W = 680, LEFT = 40, RIGHT = 90, TOP = 6, ROW = 28, AXIS = 22, BAR = 14, SLOTS = 10;
  const plotW = W - LEFT - RIGHT;

  let max = $derived(Math.max(10, Math.ceil(Math.max(0, ...legs.map((l) => l.darts)) / 10) * 10));
  let ticks = $derived(Array.from({ length: max / 10 + 1 }, (_, i) => i * 10));
  const x = (darts) => LEFT + (darts / max) * plotW;
  const when = (iso) => new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
</script>

<svg viewBox="0 0 {W} {TOP + SLOTS * ROW + AXIS}" class="chart" role="img" aria-label={t('Fastest legs won, by darts thrown')}>
  {#each ticks as tk}
    <line class="grid" x1={x(tk)} x2={x(tk)} y1={TOP} y2={TOP + SLOTS * ROW} />
    <text class="axis" x={x(tk)} y={TOP + SLOTS * ROW + 14} text-anchor="middle">{tk}</text>
  {/each}
  {#each legs as l, i}
    {@const cy = TOP + i * ROW + ROW / 2}
    <text class="rank" x="0" y={cy} dominant-baseline="central">#{i + 1}</text>
    <rect class="bar" x={LEFT} y={cy - BAR / 2} width={x(l.darts) - LEFT} height={BAR} rx="3">
      <title>{when(l.started_at)} · {l.points_start} · {t('{darts} darts · avg {avg}', { darts: l.darts, avg: l.avg3.toFixed(1) })}</title>
    </rect>
    <text class="inside" x={LEFT + 8} y={cy} dominant-baseline="central" pointer-events="none">{l.darts}</text>
    <text class="avg" x={W - RIGHT + 14} y={cy} dominant-baseline="central">Ø {l.avg3.toFixed(1)}</text>
  {/each}
</svg>

<style>
  .chart { width: 100%; height: auto; display: block; }
  .grid { stroke: var(--border); stroke-width: 1; }
  .axis { fill: var(--muted); font-size: 10px; font-variant-numeric: tabular-nums; }
  .rank { fill: var(--text); font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums; }
  .bar { fill: var(--accent); }
  .inside { fill: var(--bg); font-size: 12px; font-weight: 700; font-variant-numeric: tabular-nums; }
  .avg { fill: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; }
</style>
