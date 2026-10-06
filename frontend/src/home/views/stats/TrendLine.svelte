<script>
  import { t } from '../../../lib/i18n.js';
  // A value over a series of matches, oldest to newest: one point per match,
  // evenly spaced, with both axes labelled and the dates marked where the day
  // changes. The best and the latest value carry their number. `width` is the
  // drawing width: 360 fits a half-width card, 680 a full-width one.
  let { points = [], yTitle = '', decimals = 1, unit = '', width = 360 } = $props();

  const H = 236, RIGHT = 12, TOP = 18, BOTTOM = 34;
  let W = $derived(width);
  let LEFT = $derived(yTitle ? 40 : 32);          // room for the tick labels, and for a title if there is one
  let plotW = $derived(W - LEFT - RIGHT);
  const plotH = H - TOP - BOTTOM;

  let top = $derived.by(() => {
    const max = Math.max(0, ...points.map((p) => p.value));
    if (max <= 0) return 1;
    const exp = 10 ** Math.floor(Math.log10(max));
    return [1, 2, 5, 10].map((m) => m * exp).find((v) => max <= v);
  });
  let ticks = $derived([0, top / 2, top]);
  const x = (i) => (points.length < 2 ? LEFT + plotW / 2 : LEFT + (i / (points.length - 1)) * plotW);
  const y = (v) => TOP + plotH - (v / top) * plotH;

  let path = $derived(points.map((p, i) => `${i ? 'L' : 'M'}${x(i)},${y(p.value)}`).join(' '));
  let bestIndex = $derived(points.reduce((best, p, i) => (p.value > points[best].value ? i : best), 0));
  let labelled = $derived(new Set(points.length ? [bestIndex, points.length - 1] : []));

  // The first match of each day can get a date under the axis, as far as the dates fit side by side.
  let dayMarks = $derived.by(() => {
    const firstOfDay = points.map((p, i) => ({ i, day: p.date.slice(0, 10) }))
      .filter((m, k, all) => k === 0 || m.day !== all[k - 1].day);
    const kept = [];
    let lastX = -Infinity;
    for (const m of firstOfDay) {
      if (x(m.i) - lastX >= 46) { kept.push(m); lastX = x(m.i); }
    }
    // The latest day matters most: keep it, and let earlier dates that would touch it give way.
    const last = firstOfDay[firstOfDay.length - 1];
    if (last && !kept.includes(last)) {
      while (kept.length > 1 && x(last.i) - x(kept[kept.length - 1].i) < 46) kept.pop();
      kept.push(last);
    }
    return kept;
  });
  const dayLabel = (iso) => new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
</script>

{#if !points.length}
  <div class="empty">{t('No matches yet.')}</div>
{:else}
  <svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label={yTitle || t('Trend per match')}>
    {#if yTitle}
      <text class="axis-title" x="11" y={TOP + plotH / 2} text-anchor="middle"
            transform="rotate(-90 11 {TOP + plotH / 2})">{yTitle}</text>
    {/if}
    {#each ticks as tk}
      <line class="grid" x1={LEFT} x2={W - RIGHT} y1={y(tk)} y2={y(tk)} />
      <text class="axis" x={LEFT - 6} y={y(tk)} text-anchor="end" dominant-baseline="central">{Math.round(tk)}{unit}</text>
    {/each}
    {#each dayMarks as m}
      <line class="edge" x1={x(m.i)} x2={x(m.i)} y1={TOP + plotH} y2={TOP + plotH + 4} />
      <text class="axis" x={x(m.i)} y={TOP + plotH + 16} text-anchor="middle">{dayLabel(points[m.i].date)}</text>
    {/each}
    <path class="line" d={path} />
    {#each points as p, i}
      <circle class="point" cx={x(i)} cy={y(p.value)} r="3.5"><title>{p.tip}</title></circle>
      {#if labelled.has(i)}
        <text class="value" x={x(i)} y={y(p.value) - 8} text-anchor="middle">{p.value.toFixed(decimals)}{unit}</text>
      {/if}
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
  .line { fill: none; stroke: var(--accent); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
  .point { fill: var(--accent); stroke: var(--surface); stroke-width: 2; }
  .value { fill: var(--text); font-size: 10px; font-weight: 700; font-variant-numeric: tabular-nums; paint-order: stroke; stroke: var(--surface); stroke-width: 3px; stroke-linejoin: round; }
</style>
