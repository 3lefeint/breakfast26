<script>
  // The highest checkouts, best first: one bar per checkout, its length is the
  // points checked out on an axis from 0 and printed inside it, with the darts that
  // finished it on the right, one box per dart in a fixed column. The date and starting score are in the hover.
  let { checkouts = [] } = $props();

  const W = 680, LEFT = 40, RIGHT = 148, TOP = 6, ROW = 28, AXIS = 22, BAR = 14, SLOTS = 10, CHIP_W = 38, CHIP_H = 20, CHIP_GAP = 6;
  const plotW = W - LEFT - RIGHT;

  let high = $derived(Math.max(0, ...checkouts.map((c) => c.score)));
  let step = $derived(high > 100 ? 50 : high > 50 ? 20 : 10);
  let max = $derived(Math.max(step, Math.ceil(high / step) * step));
  let ticks = $derived(Array.from({ length: max / step + 1 }, (_, i) => i * step));
  const x = (points) => LEFT + (points / max) * plotW;
  const when = (iso) => new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
  const dart = (field) => (field === 'BULL' ? 'Bull' : field);
</script>

<svg viewBox="0 0 {W} {TOP + SLOTS * ROW + AXIS}" class="chart" role="img" aria-label="Highest checkouts">
  {#each ticks as t}
    <line class="grid" x1={x(t)} x2={x(t)} y1={TOP} y2={TOP + SLOTS * ROW} />
    <text class="axis" x={x(t)} y={TOP + SLOTS * ROW + 14} text-anchor="middle">{t}</text>
  {/each}
  {#each checkouts as c, i}
    {@const cy = TOP + i * ROW + ROW / 2}
    <text class="rank" x="0" y={cy} dominant-baseline="central">#{i + 1}</text>
    <rect class="bar" x={LEFT} y={cy - BAR / 2} width={x(c.score) - LEFT} height={BAR} rx="3">
      <title>{when(c.started_at)} · {c.points_start} · {c.score} · {c.targets.map(dart).join(' ')}</title>
    </rect>
    <text class="inside" x={LEFT + 8} y={cy} dominant-baseline="central" pointer-events="none">{c.score}</text>
    {#each c.targets as t, k}
      {@const cx = W - RIGHT + 14 + k * (CHIP_W + CHIP_GAP)}
      <rect class="chip" x={cx} y={cy - CHIP_H / 2} width={CHIP_W} height={CHIP_H} rx="5" />
      <text class="darts" x={cx + CHIP_W / 2} y={cy} text-anchor="middle" dominant-baseline="central">{dart(t)}</text>
    {/each}
  {/each}
</svg>

<style>
  .chart { width: 100%; height: auto; display: block; }
  .grid { stroke: var(--border); stroke-width: 1; }
  .axis { fill: var(--muted); font-size: 10px; font-variant-numeric: tabular-nums; }
  .rank { fill: var(--text); font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums; }
  .bar { fill: var(--accent); }
  .inside { fill: var(--bg); font-size: 12px; font-weight: 700; font-variant-numeric: tabular-nums; }
  .chip { fill: var(--bg); stroke: var(--border); stroke-width: 1; }
  .darts { fill: var(--text); font-size: 11px; }
</style>
