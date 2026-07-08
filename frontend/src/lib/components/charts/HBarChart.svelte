<script>
  // Ports index.html's hBarChartSVG().
  let { data = [], formatValue = (v, row) => v } = $props();

  const labelW = 44, valueW = 90, barH = 14, gap = 5;
  const width = 480;
  const plotW = width - labelW - valueW;
  const rowH = barH + gap;

  let height = $derived(data.length * rowH);
  let rows = $derived.by(() => {
    const max = Math.max(...data.map((d) => d.value), 1);
    return data.map((d, i) => {
      const y = i * rowH;
      const w = max ? Math.max((d.value / max) * plotW, 2) : 2;
      const valueText = String(formatValue(d.value, d));
      return { y, w, label: d.label, valueText, title: `${d.label}: ${valueText}` };
    });
  });
</script>

{#if !data.length}
  <div class="dv-empty">No data yet.</div>
{:else}
  <svg viewBox="0 0 {width} {height}" class="dv-chart" style="height:{height}px">
    {#each rows as r}
      <text x="0" y={r.y + barH * 0.8} font-size="10" fill="var(--muted)">{r.label}</text>
      <rect x={labelW} y={r.y} width={r.w} height={barH} rx="3" fill="var(--accent)"><title>{r.title}</title></rect>
      <text x={labelW + plotW + 6} y={r.y + barH * 0.8} font-size="10" fill="var(--text)">{r.valueText}</text>
    {/each}
  </svg>
{/if}

<style>
  .dv-chart { display: block; width: 100%; height: auto; }
  .dv-empty { color: var(--muted); font-size: 0.8rem; text-align: center; padding: 1rem 0; }
</style>
