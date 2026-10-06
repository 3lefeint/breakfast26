<script>
  import { t } from '../../../lib/i18n.js';
  // How often each turn score came up, in bins of ten points, with both axes
  // labelled, the count on each bar and the average marked. Bins sit between the
  // labelled edges: the bar between 20 and 30 holds the scores 20 to 29.
  let { bins = [], mean = null, yTitle = t('Turns') } = $props();

  const W = 680, H = 232, LEFT = 46, RIGHT = 10, TOP = 28, BOTTOM = 28, WIDTH = 10, AXIS_MAX = 190;
  const plotW = W - LEFT - RIGHT, plotH = H - TOP - BOTTOM;

  let total = $derived(bins.reduce((a, b) => a + b, 0));
  let top = $derived.by(() => {
    const max = Math.max(0, ...bins);
    if (max <= 0) return 1;
    const exp = 10 ** Math.floor(Math.log10(max));
    return [1, 2, 5, 10].map((m) => m * exp).find((v) => max <= v);
  });
  let ticks = $derived([0, top / 2, top]);
  let edges = $derived(Array.from({ length: 10 }, (_, i) => i * 20));      // 0, 20, ... 180

  const x = (points) => LEFT + (points / AXIS_MAX) * plotW;
  const y = (count) => TOP + plotH - (count / top) * plotH;
  const slot = plotW / (AXIS_MAX / WIDTH);

  function bar(i, count) {
    const x0 = x(i * WIDTH) + 1.5, x1 = x((i + 1) * WIDTH) - 1.5, yTop = y(count), yBase = y(0);
    const r = Math.min(3, (yBase - yTop) / 2, (x1 - x0) / 2);
    return `M${x0},${yBase} V${yTop + r} Q${x0},${yTop} ${x0 + r},${yTop} H${x1 - r} Q${x1},${yTop} ${x1},${yTop + r} V${yBase} Z`;
  }
  function describe(i, count) {
    const range = i === 18 ? '180' : `${i * WIDTH}–${i * WIDTH + WIDTH - 1}`;
    return t('{range} points: {count} {unit} ({pct}%)', { range, count, unit: count === 1 ? t('turn') : t('turns'), pct: ((count / total) * 100).toFixed(0) });
  }
</script>

{#if !total}
  <div class="empty">{t('No turns yet.')}</div>
{:else}
  <svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label={t('Histogram of turn scores')}>
    <text class="axis-title" x="11" y={TOP + plotH / 2} text-anchor="middle"
          transform="rotate(-90 11 {TOP + plotH / 2})">{yTitle}</text>
    {#each ticks as tk}
      <line class="grid" x1={LEFT} x2={W - RIGHT} y1={y(tk)} y2={y(tk)} />
      <text class="axis" x={LEFT - 6} y={y(tk)} text-anchor="end" dominant-baseline="central">{Math.round(tk)}</text>
    {/each}
    {#if mean != null}
      <line class="mean" x1={x(mean)} x2={x(mean)} y1={TOP - 6} y2={TOP + plotH} />
      <text class="mean-label" x={x(mean) + 5} y={TOP - 10} text-anchor="start">Ø {mean.toFixed(1)}</text>
    {/if}
    {#each bins as count, i}
      {#if count > 0}
        <path class="bar" d={bar(i, count)}><title>{describe(i, count)}</title></path>
        <text class="value" x={x(i * WIDTH) + slot / 2} y={y(count) - 4} text-anchor="middle">{count}</text>
      {/if}
    {/each}
    {#each edges as e}
      <line class="edge" x1={x(e)} x2={x(e)} y1={TOP + plotH} y2={TOP + plotH + 4} />
      <text class="axis" x={x(e)} y={TOP + plotH + 16} text-anchor="middle">{e}</text>
    {/each}
  </svg>
{/if}

<style>
  .empty { color: var(--muted); text-align: center; padding: 1.5rem 0; font-size: 0.8rem; }
  .chart { width: 100%; height: auto; display: block; }
  .grid { stroke: var(--border); stroke-width: 1; }
  .edge { stroke: var(--muted); stroke-width: 1; }
  .axis { fill: var(--muted); font-size: 10px; font-variant-numeric: tabular-nums; }
  .axis-title { fill: var(--muted); font-size: 11px; }
  .value { fill: var(--text); font-size: 10px; font-weight: 600; font-variant-numeric: tabular-nums; paint-order: stroke; stroke: var(--surface); stroke-width: 3px; stroke-linejoin: round; }
  .bar { fill: var(--accent); }
  .mean { stroke: var(--text); stroke-width: 1.5; stroke-dasharray: 4 3; }
  .mean-label { fill: var(--text); font-size: 11px; font-weight: 700; }
</style>
