<script>
  import { t } from '../../../lib/i18n.js';
  // A donut with the share in the middle. Hovering a segment gives its count.
  let { segments = [], centerValue = '', centerLabel = '' } = $props();

  // Same drawing size and outer radius as the doubles radar, so the two line up.
  const SIZE = 440, MID = SIZE / 2, STROKE = 6, R = 150 - STROKE / 2, C = 2 * Math.PI * R, GAP = 6;
  let total = $derived(segments.reduce((a, s) => a + s.value, 0));
  let arcs = $derived.by(() => {
    let offset = 0;
    return segments.filter((s) => s.value > 0).map((s) => {
      const length = (s.value / total) * C;
      const arc = { ...s, length: Math.max(length - GAP, 0.5), offset };
      offset += length;
      return arc;
    });
  });
</script>

{#if !total}
  <div class="empty">{t('Nothing decided yet.')}</div>
{:else}
  <div class="donut">
    <svg viewBox="0 0 {SIZE} {SIZE}" class="ring" role="img"
         aria-label={segments.map((s) => `${s.label} ${s.value}`).join(', ')}>
      <g transform="rotate(-90 {MID} {MID})">
        {#each arcs as a}
          <circle cx={MID} cy={MID} r={R} fill="none" stroke={a.color} stroke-width={STROKE}
                  stroke-dasharray="{a.length} {C - a.length}" stroke-dashoffset={-a.offset}>
            <title>{a.label}: {a.value} ({((a.value / total) * 100).toFixed(0)}%)</title>
          </circle>
        {/each}
      </g>
      <text class="center-value" x={MID} y={MID - 10} text-anchor="middle" dominant-baseline="central">{centerValue}</text>
      <text class="center-label" x={MID} y={MID + 26} text-anchor="middle">{centerLabel}</text>
    </svg>
  </div>
{/if}

<style>
  .empty { color: var(--muted); text-align: center; padding: 1.5rem 0; font-size: 0.8rem; }
  .donut { display: flex; justify-content: center; align-items: center; width: 100%; height: 100%; }
  .ring { height: 100%; max-width: 100%; aspect-ratio: 1; }
  .center-value { fill: var(--text); font-size: 40px; font-weight: 700; }
  .center-label { fill: var(--muted); font-size: 16px; }
</style>
