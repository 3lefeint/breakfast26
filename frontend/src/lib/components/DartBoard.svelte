<script>
  // Clickable dartboard: a click turns into the same field string the
  // correction endpoints already accept (`T20`, `D16`, `25`, `50`, `0`).
  import { SEGMENT_ORDER, RINGS_MM, fieldAtMm } from '../dartboard.js';

  let { onSelect, disabled = false } = $props();

  const HALF = 200;           // viewBox is -200..200 on both axes
  const BOARD_R = 165;        // rendered radius of the double ring's outer edge
  const K = BOARD_R / RINGS_MM.DOUBLE_OUT;

  let hover = $state('');

  function point(rMm, deg) {
    const a = (deg * Math.PI) / 180;
    return [rMm * K * Math.sin(a), -rMm * K * Math.cos(a)];
  }

  function band(rInMm, rOutMm, a0, a1) {
    const [x0, y0] = point(rOutMm, a0);
    const [x1, y1] = point(rOutMm, a1);
    const [x2, y2] = point(rInMm, a1);
    const [x3, y3] = point(rInMm, a0);
    const rOut = rOutMm * K, rIn = rInMm * K;
    return `M${x0},${y0} A${rOut},${rOut} 0 0 1 ${x1},${y1} L${x2},${y2} A${rIn},${rIn} 0 0 0 ${x3},${y3} Z`;
  }

  const segments = SEGMENT_ORDER.map((n, i) => {
    const a0 = i * 18 - 9, a1 = i * 18 + 9;
    const dark = i % 2 === 0;
    const [tx, ty] = point(RINGS_MM.DOUBLE_OUT + 14, i * 18);
    return {
      n, tx, ty,
      single: dark ? '#1d1d22' : '#e6dcc0',
      ring: dark ? '#b8372c' : '#2f8a5a',
      outer: band(RINGS_MM.DOUBLE_IN, RINGS_MM.DOUBLE_OUT, a0, a1),
      triple: band(RINGS_MM.TRIPLE_IN, RINGS_MM.TRIPLE_OUT, a0, a1),
      outerSingle: band(RINGS_MM.TRIPLE_OUT, RINGS_MM.DOUBLE_IN, a0, a1),
      innerSingle: band(RINGS_MM.OUTER_BULL, RINGS_MM.TRIPLE_IN, a0, a1),
    };
  });

  function fieldFromEvent(e) {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * (2 * HALF) - HALF;
    const y = ((e.clientY - rect.top) / rect.height) * (2 * HALF) - HALF;
    return fieldAtMm(x / K, y / K);
  }

  function labelFor(field) {
    if (!field) return '';
    if (field === '0') return 'Miss';
    if (field === '25') return 'Bull (25)';
    if (field === '50') return 'D-Bull (50)';
    return field;
  }
</script>

<div class="board-wrap" class:disabled>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <svg viewBox="{-HALF} {-HALF} {2 * HALF} {2 * HALF}" class="dartboard"
       aria-label="Dartboard: click where the dart landed"
       onclick={(e) => !disabled && onSelect(fieldFromEvent(e))}
       onpointermove={(e) => { hover = disabled ? '' : fieldFromEvent(e); }}
       onpointerleave={() => (hover = '')}>
    <circle r={BOARD_R + 4} fill="#0c0c0f" />
    {#each segments as s}
      <path d={s.innerSingle} fill={s.single} />
      <path d={s.outerSingle} fill={s.single} />
      <path d={s.triple} fill={s.ring} />
      <path d={s.outer} fill={s.ring} />
      <text x={s.tx} y={s.ty} class="num">{s.n}</text>
    {/each}
    <circle r={RINGS_MM.OUTER_BULL * K} fill="#2f8a5a" />
    <circle r={RINGS_MM.BULL * K} fill="#b8372c" />
    <g class="wires" fill="none">
      {#each [RINGS_MM.TRIPLE_IN, RINGS_MM.TRIPLE_OUT, RINGS_MM.DOUBLE_IN, RINGS_MM.DOUBLE_OUT, RINGS_MM.OUTER_BULL] as r}
        <circle r={r * K} />
      {/each}
    </g>
  </svg>
  <div class="hover-label">{labelFor(hover) || ' '}</div>
</div>

<style>
  .board-wrap { display: flex; flex-direction: column; align-items: center; }
  .dartboard { width: 100%; max-width: 380px; height: auto; cursor: crosshair; touch-action: manipulation; }
  .disabled .dartboard { cursor: default; opacity: 0.4; }
  .num { fill: var(--muted); font-size: 16px; font-weight: 600; text-anchor: middle; dominant-baseline: central; pointer-events: none; }
  .wires circle { stroke: rgba(255, 255, 255, 0.18); stroke-width: 0.6; pointer-events: none; }
  .hover-label { margin-top: 0.3rem; font-size: 0.85rem; color: var(--muted); min-height: 1.2em; }
</style>
