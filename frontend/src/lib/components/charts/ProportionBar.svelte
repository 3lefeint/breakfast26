<script>
  // Ports index.html's proportionBarSVG().
  let { segments = [] } = $props();

  const width = 300, height = 22, gap = 2;

  let total = $derived(segments.reduce((s, x) => s + x.value, 0));
  let rects = $derived.by(() => {
    if (!total) return [];
    let xOff = 0;
    return segments
      .filter((s) => s.value > 0)
      .map((seg) => {
        const w = Math.max((seg.value / total) * width - gap, 0);
        const rect = { x: xOff, w, color: seg.color, title: `${seg.label}: ${seg.value}` };
        xOff += (seg.value / total) * width;
        return rect;
      });
  });
</script>

{#if !total}
  <div class="dv-empty">No data yet.</div>
{:else}
  <svg viewBox="0 0 {width} {height}" class="dv-chart" style="height:{height}px">
    {#each rects as r}
      <rect x={r.x} y="0" width={r.w} height={height} rx="3" fill={r.color}><title>{r.title}</title></rect>
    {/each}
  </svg>
{/if}

<style>
  .dv-chart { display: block; width: 100%; height: auto; }
  .dv-empty { color: var(--muted); font-size: 0.8rem; text-align: center; padding: 1rem 0; }
</style>
