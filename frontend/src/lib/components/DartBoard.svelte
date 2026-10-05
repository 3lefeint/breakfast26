<script>
  // Dartboard. By default a click turns into the same field string the
  // correction endpoints already accept (`T20`, `D16`, `25`, `50`, `0`).
  // With `readonly` it only displays `darts` ({ n, x, y }, unit = outer edge
  // of the double ring, y up) as numbered markers.
  import { SEGMENT_ORDER, RINGS_MM, fieldAtMm } from '../dartboard.js';
  import AvatarArt from './AvatarArt.svelte';

  // Optional extras for games that play on the board: a dart can carry its own `color` (and a
  // `ring` of { color, dash } to tell players of similar colors apart, and a `label` instead of the
  // number, or `dot` for a small dot, `scored` makes it the accent color, or `avatar` ({ name, color })
  // to show the avatar of the player with the `label` in its center), `highlight` marks the
  // field of one number and dims the rest, `pointer` ({ angle, ms }) draws a needle from the
  // center that turns to `angle` degrees clockwise from the top in `ms` milliseconds.
  //
  // `zones` colors parts of the board: [{ n, color, parts, level }], `parts` any of 'double',
  // 'outerSingle', 'innerSingle', 'triple' (or 'all'), `level` 'strong' (what is open, pulses),
  // 'owned' (the field of a number that belongs to a player), 'danger' (a hit costs you, red
  // dashed) or 'dead' (darkened).
  let { onSelect, disabled = false, readonly = false, darts = [], highlight = null, pointer = null,
        zones = [] } = $props();

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

  const R = BOARD_R + 4;
  const disc = `M${-R},0 A${R},${R} 0 1 0 ${R},0 A${R},${R} 0 1 0 ${-R},0 Z`;
  let highlightPath = $derived.by(() => {
    const i = SEGMENT_ORDER.indexOf(highlight);
    return i < 0 ? null : band(RINGS_MM.OUTER_BULL, RINGS_MM.DOUBLE_OUT, i * 18 - 9, i * 18 + 9);
  });

  // Dark text on a light marker, light text on a dark one.
  function labelColor(color) {
    if (!color || !/^#[0-9a-f]{6}$/i.test(color)) return '#0c0c0f';
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16));
    return 0.299 * r + 0.587 * g + 0.114 * b > 140 ? '#0c0c0f' : '#ffffff';
  }

  const PARTS = ['double', 'outerSingle', 'triple', 'innerSingle'];

  // The zones as paths to draw: one per part of every zone.
  let zonePaths = $derived(zones.flatMap((z) => {
    const seg = segments[SEGMENT_ORDER.indexOf(z.n)];
    if (!seg) return [];
    const parts = z.parts === 'all' || !z.parts ? PARTS : z.parts;
    const map = { double: seg.outer, outerSingle: seg.outerSingle, triple: seg.triple, innerSingle: seg.innerSingle };
    return parts.map((part) => ({ key: `${z.n}-${z.level || "strong"}-${part}`, d: map[part], color: z.color, level: z.level || 'strong' }));
  }));

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

<div class="board-wrap" class:disabled class:readonly>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <svg viewBox="{-HALF} {-HALF} {2 * HALF} {2 * HALF}" class="dartboard"
       aria-label={readonly ? 'Dartboard: darts on the board' : 'Dartboard: click where the dart landed'}
       onclick={(e) => !readonly && !disabled && onSelect(fieldFromEvent(e))}
       onpointermove={(e) => { hover = readonly || disabled ? '' : fieldFromEvent(e); }}
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
    {#each zonePaths as z (z.key)}
      <path class="zone {z.level}" d={z.d} style="--zone: {z.color || 'var(--accent)'}" />
    {/each}
    {#if highlightPath}
      <path class="dim" d="{disc} {highlightPath}" fill-rule="evenodd" />
      <path class="highlight" d={highlightPath} />
    {/if}
    {#if pointer}
      <g class="pointer" style="transform: rotate({pointer.angle}deg); transition: transform {pointer.ms}ms cubic-bezier(0.15, 0.7, 0.15, 1)">
        <line x1="0" y1="0" x2="0" y2={-(BOARD_R - 10)} />
        <path d="M-10,{-(BOARD_R + 16)} L10,{-(BOARD_R + 16)} L0,{-(BOARD_R - 6)} Z" />
        <circle r="9" />
      </g>
    {/if}
    {#each darts.filter((d) => d.x != null) as d (d.n)}
      <g class="dart" style="transform: translate({d.x * BOARD_R}px, {-d.y * BOARD_R}px)">
        {#if d.ring}
          <circle class="dart-ring" r="16.5" style="stroke: {d.ring.color}" stroke-dasharray={d.ring.dash ? '5 3' : null} />
        {/if}
        {#if d.avatar}
          {#if d.ring}
            <circle class="dart-ring" r="15.5" style="stroke: {d.ring.color}" stroke-dasharray={d.ring.dash ? '5 3' : null} />
          {/if}
          <circle class="avatar-back" r="13" />
          <svg x="-12" y="-12" width="24" height="24" viewBox="-50 -50 100 100"><AvatarArt name={d.avatar.name} color={d.avatar.color} /></svg>
          {#if d.label != null && d.label !== ''}
            <text class="avatar-n">{d.label}</text>
          {/if}
        {:else if d.dot}
          <circle class="dart-dot" class:scored={d.scored > 0} r="5" />
        {:else}
          <circle r="12" style={d.color ? `fill: ${d.color}` : null} />
          <text class="dart-n" style={d.color ? `fill: ${labelColor(d.color)}` : null}>{d.label ?? d.n}</text>
        {/if}
      </g>
    {/each}
  </svg>
  {#if !readonly}<div class="hover-label">{labelFor(hover) || ' '}</div>{/if}
</div>

<style>
  .board-wrap { display: flex; flex-direction: column; align-items: center; width: 100%; }
  .dartboard { width: 100%; max-width: var(--board-max, 380px); height: auto; cursor: crosshair; touch-action: manipulation; overflow: visible; }
  .disabled .dartboard { cursor: default; opacity: 0.4; }
  .readonly .dartboard { cursor: default; }
  .num { fill: var(--muted); font-size: 16px; font-weight: 600; text-anchor: middle; dominant-baseline: central; pointer-events: none; }
  .wires circle { stroke: rgba(255, 255, 255, 0.18); stroke-width: 0.6; pointer-events: none; }
  .dart { transition: transform 0.25s ease-out; pointer-events: none; }
  .dart circle { fill: var(--accent); stroke: #0c0c0f; stroke-width: 1.5; }
  .dart-ring { fill: none; stroke-width: 3; }
  .dart .avatar-back { fill: #0c0c0f; stroke: rgba(255, 255, 255, 0.85); stroke-width: 2; }
  .avatar-n { fill: #fff; stroke: #0c0c0f; stroke-width: 3px; paint-order: stroke; stroke-linejoin: round; font-size: 13px; font-weight: 900; text-anchor: middle; dominant-baseline: central; }
  .dart .dart-dot { fill: rgba(255, 255, 255, 0.7); stroke-width: 1; opacity: 0.8; }
  .dart .dart-dot.scored { fill: var(--accent); }
  .dim { fill: rgba(8, 8, 12, 0.45); pointer-events: none; }
  .highlight { fill: rgba(255, 255, 255, 0.16); stroke: var(--accent); stroke-width: 3; pointer-events: none; }
  .zone { pointer-events: none; stroke: var(--zone); stroke-width: 3; fill: color-mix(in srgb, var(--zone) 80%, transparent); filter: drop-shadow(0 0 5px var(--zone)); }
  .zone.owned { fill: color-mix(in srgb, var(--zone) 50%, transparent); stroke-width: 0; filter: none; }
  .zone.dead { fill: rgba(8, 8, 12, 0.6); stroke: none; }
  .zone.danger { fill: rgba(239, 68, 68, 0.2); stroke: #ef4444; stroke-dasharray: 5 3; }
  .zone.strong { animation: zone-pulse 1.6s ease-in-out infinite; }
  @keyframes zone-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.55; } }
  .pointer { pointer-events: none; }
  .pointer line { stroke: var(--accent); stroke-width: 4; stroke-linecap: round; }
  .pointer path { fill: var(--accent); stroke: #0c0c0f; stroke-width: 1.5; stroke-linejoin: round; }
  .pointer circle { fill: var(--accent); stroke: #0c0c0f; stroke-width: 2; }
  .dart-n { fill: #0c0c0f; font-size: 14px; font-weight: 800; text-anchor: middle; dominant-baseline: central; }
  .hover-label { margin-top: 0.3rem; font-size: 0.85rem; color: var(--muted); min-height: 1.2em; }
</style>
