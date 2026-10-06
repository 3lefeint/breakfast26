<script>
  import { t } from '../../../lib/i18n.js';
  // Bars for the days someone played, with a labelled axis and the value on
  // each bar. Days without play are left out instead of stretching the axis, so
  // a few sessions months apart stay readable.
  let { data = [], unit = '' } = $props();

  const W = 400, H = 170, LEFT = 38, TOP = 18, BOTTOM = 24, MAX_BARS = 12;
  const plotH = H - TOP - BOTTOM;
  const plotW = W - LEFT - 8;

  let days = $derived(data.filter((d) => d.value > 0).slice(-MAX_BARS));
  let top = $derived.by(() => {
    const max = Math.max(0, ...days.map((d) => d.value));
    if (max <= 0) return 1;
    const exp = 10 ** Math.floor(Math.log10(max));
    return [1, 2, 5, 10].map((m) => m * exp).find((v) => max <= v);
  });
  let ticks = $derived([0, top / 2, top]);
  let slot = $derived(plotW / Math.max(days.length, 1));
  let barW = $derived(Math.min(34, slot * 0.6));

  const y = (v) => TOP + plotH - (v / top) * plotH;
  const dateLabel = (iso) => new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
  const dateFull = (iso) => new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });

  // A bar with rounded top corners and a square foot on the baseline.
  function bar(cx, v) {
    const x0 = cx - barW / 2, x1 = cx + barW / 2, yTop = y(v), yBase = y(0);
    const r = Math.min(4, (yBase - yTop) / 2, barW / 2);
    return `M${x0},${yBase} V${yTop + r} Q${x0},${yTop} ${x0 + r},${yTop} H${x1 - r} Q${x1},${yTop} ${x1},${yTop + r} V${yBase} Z`;
  }
</script>

{#if !days.length}
  <div class="empty">{t('No data yet.')}</div>
{:else}
  <svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label={t('{unit} per day played', { unit })}>
    {#each ticks as tk}
      <line class="grid" x1={LEFT} x2={W - 8} y1={y(tk)} y2={y(tk)} />
      <text class="axis" x={LEFT - 6} y={y(tk)} text-anchor="end" dominant-baseline="central">{Math.round(tk)}</text>
    {/each}
    {#each days as d, i (d.label)}
      {@const cx = LEFT + slot * i + slot / 2}
      <path class="bar" d={bar(cx, d.value)}><title>{dateFull(d.label)}: {Math.round(d.value)} {unit}</title></path>
      <text class="value" x={cx} y={y(d.value) - 5} text-anchor="middle">{Math.round(d.value)}</text>
      <text class="axis" x={cx} y={H - 7} text-anchor="middle">{dateLabel(d.label)}</text>
    {/each}
  </svg>
{/if}

<style>
  .empty { color: var(--muted); text-align: center; padding: 1rem 0; font-size: 0.8rem; }
  .chart { width: 100%; height: auto; display: block; }
  .grid { stroke: var(--border); stroke-width: 1; }
  .axis { fill: var(--muted); font-size: 10px; font-variant-numeric: tabular-nums; }
  .value { fill: var(--text); font-size: 11px; font-weight: 600; font-variant-numeric: tabular-nums; }
  .bar { fill: var(--accent); }
</style>
