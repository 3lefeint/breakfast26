<script>
  // The hit rate of every double as a radar: the doubles sit around the circle in
  // board order starting with 20 at the top, the distance from the centre is the
  // share of attempts that were hit. The rings carry the percentages.
  import { SEGMENT_ORDER } from '../../../lib/dartboard.js';

  let { doubles = [] } = $props();

  const SIZE = 440, C = SIZE / 2, R = 150, LABEL_R = R + 20;

  let byNumber = $derived(new Map(doubles.map((d) => [d.target, d])));
  let spokes = $derived(SEGMENT_ORDER.map((n, i) => {
    const d = byNumber.get(n);
    return { n, i, attempts: d?.attempts ?? 0, hits: d?.hits ?? 0, pct: d?.pct ?? 0 };
  }));
  let top = $derived.by(() => {
    const max = Math.max(0, ...spokes.map((s) => s.pct));
    return Math.max(5, Math.ceil(max / 5) * 5);                       // rings in steps of 5%
  });
  let rings = $derived([1, 2, 3, 4].map((k) => (top / 4) * k));

  const angle = (i) => (i * 18 * Math.PI) / 180;
  const at = (i, radius) => [C + radius * Math.sin(angle(i)), C - radius * Math.cos(angle(i))];
  const ringPoints = (value) => spokes.map((s) => at(s.i, (value / top) * R).join(',')).join(' ');
  let shape = $derived(spokes.map((s) => at(s.i, (s.pct / top) * R).join(',')).join(' '));
  const tip = (s) => `D${s.n}: ${s.hits} of ${s.attempts} hit (${s.pct.toFixed(0)}%)`;
</script>

{#if !doubles.some((d) => d.attempts > 0)}
  <div class="empty">No double attempts yet.</div>
{:else}
  <div class="radar">
  <svg viewBox="0 0 {SIZE} {SIZE}" class="chart" role="img" aria-label="Hit rate per double, around the board">
    {#each rings as r}
      <polygon class="ring" points={ringPoints(r)} />
    {/each}
    {#each spokes as s}
      <line class="spoke" x1={C} y1={C} x2={at(s.i, R)[0]} y2={at(s.i, R)[1]} />
      <text class="num" x={at(s.i, LABEL_R)[0]} y={at(s.i, LABEL_R)[1]} text-anchor="middle" dominant-baseline="central">{s.n}</text>
    {/each}
    <polygon class="shape" points={shape} />
    {#each spokes as s}
      {#if s.attempts > 0}
        <circle class="dot" cx={at(s.i, (s.pct / top) * R)[0]} cy={at(s.i, (s.pct / top) * R)[1]} r="3.5"><title>{tip(s)}</title></circle>
      {/if}
    {/each}
    {#each rings as r}
      <text class="scale" x={C + 4} y={C - (r / top) * R - 2}>{Math.round(r)}%</text>
    {/each}
  </svg>
  </div>
{/if}

<style>
  .empty { color: var(--muted); text-align: center; padding: 1.5rem 0; font-size: 0.8rem; }
  .radar { display: flex; flex-direction: column; align-items: center; width: 100%; height: 100%; min-height: 0; }
  .chart { display: block; flex: 1; min-height: 0; width: 100%; max-width: 30rem; margin: 0 auto; }
  .ring { fill: none; stroke: var(--border); stroke-width: 1; }
  .spoke { stroke: var(--border); stroke-width: 1; }
  .num { fill: var(--muted); font-size: 13px; font-weight: 600; }
  .scale { fill: var(--muted); font-size: 10px; font-variant-numeric: tabular-nums; }
  .shape { fill: color-mix(in srgb, var(--accent) 28%, transparent); stroke: var(--accent); stroke-width: 2; stroke-linejoin: round; }
  .dot { fill: var(--accent); stroke: var(--surface); stroke-width: 1.5; }
</style>
