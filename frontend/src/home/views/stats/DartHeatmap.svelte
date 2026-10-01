<script>
  // Where the darts went: every field of the board shaded by how often it was
  // hit, and a ring outside the board for the darts that missed it, by sector.
  // Shading follows the square root of the count so the rarely hit fields still
  // show next to a favourite one; hovering a field gives its count.
  import { SEGMENT_ORDER, RINGS_MM, bandPath, polar } from '../../../lib/dartboard.js';

  let { fields = {}, misses = {}, darts = 0 } = $props();

  const HALF = 192, BOARD_R = 150;      // the number labels reach out to about 185
  const K = BOARD_R / RINGS_MM.DOUBLE_OUT;
  const MISS_IN = RINGS_MM.DOUBLE_OUT + 4, MISS_OUT = RINGS_MM.DOUBLE_OUT + 17;
  const LABEL_R = RINGS_MM.DOUBLE_OUT + 32;

  let maxHit = $derived(Math.max(0, ...Object.values(fields)));
  let maxMiss = $derived(Math.max(0, ...Object.values(misses)));

  function shade(count, max, hue) {
    if (!count || !max) return 'var(--surface)';
    const strength = Math.round(12 + Math.sqrt(count / max) * 88);
    return `color-mix(in srgb, ${hue} ${strength}%, var(--surface))`;
  }
  const hits = (field) => fields[field] ?? 0;
  const pct = (n) => (darts ? ((n / darts) * 100).toFixed(1) : '0');
  const tip = (label, n) => `${label}: ${n} ${n === 1 ? 'dart' : 'darts'} (${pct(n)}%)`;

  let sectors = $derived(SEGMENT_ORDER.map((n, i) => {
    const a0 = i * 18 - 9, a1 = i * 18 + 9;
    const single = hits('S' + n);
    return {
      n, i,
      single: { fill: shade(single, maxHit, 'var(--accent)'), tip: tip(`S${n} (inner and outer single)`, single),
                inner: bandPath(RINGS_MM.OUTER_BULL, RINGS_MM.TRIPLE_IN, a0, a1, K),
                outer: bandPath(RINGS_MM.TRIPLE_OUT, RINGS_MM.DOUBLE_IN, a0, a1, K) },
      triple: { fill: shade(hits('T' + n), maxHit, 'var(--accent)'), tip: tip('T' + n, hits('T' + n)),
                path: bandPath(RINGS_MM.TRIPLE_IN, RINGS_MM.TRIPLE_OUT, a0, a1, K) },
      double: { fill: shade(hits('D' + n), maxHit, 'var(--accent)'), tip: tip('D' + n, hits('D' + n)),
                path: bandPath(RINGS_MM.DOUBLE_IN, RINGS_MM.DOUBLE_OUT, a0, a1, K) },
      miss: { fill: shade(misses[n], maxMiss, 'var(--red)'), tip: tip(`Missed next to ${n}`, misses[n] ?? 0),
              path: bandPath(MISS_IN, MISS_OUT, a0, a1, K) },
      label: polar(LABEL_R, i * 18, K),
    };
  }));
</script>

{#if !darts}
  <div class="empty">No darts recorded yet.</div>
{:else}
  <div class="wrap">
    <svg viewBox="{-HALF} {-HALF} {2 * HALF} {2 * HALF}" class="board" role="img"
         aria-label="Dartboard shaded by how often each field was hit">
      <circle r={MISS_OUT * K + 4} fill="var(--bg)" />
      {#each sectors as s (s.n)}
        <path d={s.miss.path} fill={s.miss.fill} class="cell"><title>{s.miss.tip}</title></path>
        <path d={s.single.inner} fill={s.single.fill} class="cell"><title>{s.single.tip}</title></path>
        <path d={s.single.outer} fill={s.single.fill} class="cell"><title>{s.single.tip}</title></path>
        <path d={s.triple.path} fill={s.triple.fill} class="cell"><title>{s.triple.tip}</title></path>
        <path d={s.double.path} fill={s.double.fill} class="cell"><title>{s.double.tip}</title></path>
        <text class="num" x={s.label[0]} y={s.label[1]}>{s.n}</text>
      {/each}
      <circle r={RINGS_MM.OUTER_BULL * K} fill={shade(hits('25'), maxHit, 'var(--accent)')} class="cell">
        <title>{tip('25 (single bull)', hits('25'))}</title>
      </circle>
      <circle r={RINGS_MM.BULL * K} fill={shade(hits('BULL'), maxHit, 'var(--accent)')} class="cell">
        <title>{tip('Bull (50)', hits('BULL'))}</title>
      </circle>
    </svg>
  </div>
{/if}

<style>
  .empty { color: var(--muted); text-align: center; padding: 1.5rem 0; font-size: 0.8rem; }
  .wrap { display: flex; justify-content: center; }
  .board { width: 100%; max-width: 32rem; height: auto; }
  .cell { stroke: var(--bg); stroke-width: 0.8; }
  .num { fill: var(--muted); font-size: 13px; font-weight: 600; text-anchor: middle; dominant-baseline: central; pointer-events: none; }
</style>
