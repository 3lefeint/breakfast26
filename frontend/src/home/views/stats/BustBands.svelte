<script>
  // For each range of starting scores: the share of turns that ended in a bust,
  // as a bar on a 0 to 100% axis, with the busts and turns behind it.
  let { bands = [] } = $props();

  const W = 680, LEFT = 66, RIGHT = 118, TOP = 6, ROW = 28, AXIS = 22, BAR = 14;
  const plotW = W - LEFT - RIGHT;
  const TICKS = [0, 25, 50, 75, 100];

  let height = $derived(TOP + bands.length * ROW + AXIS);
  const x = (percent) => LEFT + (percent / 100) * plotW;
  const rate = (b) => (b.turns ? (b.busts / b.turns) * 100 : null);
</script>

<svg viewBox="0 0 {W} {height}" class="chart" role="img" aria-label="Bust rate by starting score">
  {#each TICKS as t}
    <line class="grid" x1={x(t)} x2={x(t)} y1={TOP} y2={TOP + bands.length * ROW} />
    <text class="axis" x={x(t)} y={TOP + bands.length * ROW + 14} text-anchor="middle">{t}%</text>
  {/each}
  {#each bands as b, i}
    {@const cy = TOP + i * ROW + ROW / 2}
    {@const r = rate(b)}
    <text class="label" x={LEFT - 10} y={cy} text-anchor="end" dominant-baseline="central">{b.label}</text>
    {#if r !== null && r > 0}
      <rect class="bar" x={LEFT} y={cy - BAR / 2} width={Math.max(x(r) - LEFT, 3)} height={BAR} rx="3">
        <title>{b.busts} of {b.turns} turns started at {b.label} ended in a bust ({r.toFixed(0)}%)</title>
      </rect>
    {/if}
    <text class="value" x={W - RIGHT + 14} y={cy} dominant-baseline="central">
      {#if r === null}—{:else}<tspan class="strong">{r.toFixed(0)}%</tspan><tspan class="sub" dx="8">{b.busts}/{b.turns}</tspan>{/if}
    </text>
  {/each}
</svg>

<style>
  .chart { width: 100%; height: auto; display: block; }
  .grid { stroke: var(--border); stroke-width: 1; }
  .axis { fill: var(--muted); font-size: 10px; font-variant-numeric: tabular-nums; }
  .label { fill: var(--text); font-size: 12px; font-weight: 600; }
  .bar { fill: var(--accent); }
  .value { fill: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; }
  .value .strong { fill: var(--text); font-weight: 700; }
  .value .sub { fill: var(--muted); font-size: 11px; }
</style>
