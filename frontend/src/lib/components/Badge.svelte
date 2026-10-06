<script>
  import { t } from '../i18n.js';
  // One achievement badge: the motif image inside a round rim. The rim shows the
  // difficulty (plain, bronze with one notch, silver with two, gold with three, gold
  // with a crown, or segments that fill with each tier), the label (a number) is
  // drawn over the motif. Locked badges are dimmed, a secret one shows a question mark.
  // An achievement whose motif has not been made yet shows a star instead.
  import { motifUrl, isEarned, localized } from '../achievements.js';

  let { item, size = 72 } = $props();

  const CENTER = 50;
  const RIM_R = 46;
  const RIM_COLOURS = {
    easy: '#555b70', medium: '#cd7f32', hard: '#c4c9d6', very_hard: '#ffd54a',
    extreme: '#ffd54a', endurance: '#555b70', hidden: '#555b70',
  };
  const NOTCHES = { medium: 1, hard: 2, very_hard: 3 };
  const SEGMENT_GAP_DEG = 8;
  // A five-pointed star around (50, 47), the placeholder while there is no motif.
  const STAR = Array.from({ length: 10 }, (_, i) => {
    const r = i % 2 === 0 ? 27 : 11;
    const a = ((i * 36 - 90) * Math.PI) / 180;
    return `${(50 + r * Math.cos(a)).toFixed(1)},${(47 + r * Math.sin(a)).toFixed(1)}`;
  }).join(' ');

  let earned = $derived(isEarned(item));
  let secret = $derived(item.hidden && !earned);
  let url = $derived(motifUrl(item.motif || item.id));
  let rim = $derived(RIM_COLOURS[item.difficulty] || RIM_COLOURS.easy);
  let notches = $derived(NOTCHES[item.difficulty] || 0);
  let crown = $derived(item.difficulty === 'extreme');
  let segments = $derived(item.difficulty === 'endurance' && item.tiers ? item.tiers.length : 0);
  let name = $derived(localized(item.names) || t('Secret achievement'));

  function point(deg, r) {
    const rad = ((deg - 90) * Math.PI) / 180;
    return [CENTER + r * Math.cos(rad), CENTER + r * Math.sin(rad)];
  }

  function arc(from, to) {
    const [x1, y1] = point(from, RIM_R);
    const [x2, y2] = point(to, RIM_R);
    return `M ${x1} ${y1} A ${RIM_R} ${RIM_R} 0 ${to - from > 180 ? 1 : 0} 1 ${x2} ${y2}`;
  }

  let segmentArcs = $derived(
    Array.from({ length: segments }, (_, i) => {
      const span = 360 / segments;
      return { d: arc(i * span + SEGMENT_GAP_DEG / 2, (i + 1) * span - SEGMENT_GAP_DEG / 2), on: i < item.tier };
    })
  );

  // Notches sit on the top of the rim, centred around 12 o'clock.
  let notchPoints = $derived(
    Array.from({ length: notches }, (_, i) => point((i - (notches - 1) / 2) * 16, RIM_R))
  );
</script>

<svg class="badge" class:locked={!earned} viewBox="0 0 100 100" width={size} height={size}
     role="img" aria-label={name}>
  <circle cx={CENTER} cy={CENTER} r="42" class="disc" />
  {#if secret}
    <text x={CENTER} y="64" text-anchor="middle" class="secret">?</text>
  {:else}
    {#if url}
      <image href={url} x="12" y="12" width="76" height="76" class="motif" />
    {:else}
      <polygon points={STAR} class="placeholder" />
    {/if}
    {#if item.label}
      <text x={CENTER} y="84" text-anchor="middle" class="label">{item.label}</text>
    {/if}
  {/if}

  {#if segments}
    {#each segmentArcs as seg}
      <path d={seg.d} class="segment" class:on={seg.on} fill="none" stroke-linecap="round" />
    {/each}
  {:else}
    <circle cx={CENTER} cy={CENTER} r={RIM_R} fill="none" stroke={rim} stroke-width="5"
            opacity={earned || secret ? 1 : 0.25} />
    {#each notchPoints as [x, y]}
      <circle cx={x} cy={y} r="3.2" class="notch" />
    {/each}
  {/if}

  {#if crown}
    <path class="crown" d="M38 8 L42 15 L50 5 L58 15 L62 8 L61 19 L39 19 Z" />
  {/if}

  {#if earned && item.tiers}
    <circle cx="82" cy="82" r="13" class="tier-dot" />
    <text x="82" y="87.5" text-anchor="middle" class="tier-text">{item.tier}</text>
  {/if}
</svg>

<style>
  .badge { flex-shrink: 0; }
  .disc { fill: var(--bg); }
  .motif { transition: opacity 0.2s, filter 0.2s; }
  .locked .motif { opacity: 0.3; filter: grayscale(1); }
  .placeholder { fill: var(--muted); opacity: 0.6; stroke: var(--muted); stroke-width: 3px; stroke-linejoin: round; }
  .locked .placeholder { opacity: 0.3; }
  .label {
    font: 800 20px system-ui, sans-serif; fill: #fff;
    stroke: #000; stroke-width: 4px; paint-order: stroke; stroke-linejoin: round;
  }
  .locked .label { opacity: 0.5; }
  .secret { font: 800 46px system-ui, sans-serif; fill: var(--muted); }
  .segment { stroke: var(--border); stroke-width: 5px; }
  .segment.on { stroke: var(--accent); }
  .notch { fill: var(--surface); }
  .locked .crown { opacity: 0.25; }
  .crown { fill: #ffd54a; stroke: #7a5b00; stroke-width: 1.5px; stroke-linejoin: round; }
  .tier-dot { fill: var(--accent); stroke: var(--surface); stroke-width: 2px; }
  .tier-text { font: 800 16px system-ui, sans-serif; fill: var(--bg); }
</style>
