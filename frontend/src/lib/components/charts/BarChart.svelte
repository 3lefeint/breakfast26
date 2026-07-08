<script>
  // Ports index.html's barChartSVG() to a real Svelte template. Minimal
  // inline-SVG chart, no charting library — matches the app's existing
  // no-build-step/no-CDN style (now just built via Vite instead).
  let { data = [], formatValue = (v) => v } = $props();

  const width = 480, height = 130, padL = 4, padR = 4, padT = 8, padB = 18;
  const plotW = width - padL - padR, plotH = height - padT - padB;

  let bars = $derived.by(() => {
    const max = Math.max(...data.map((d) => d.value), 1);
    const slot = plotW / data.length;
    const barW = Math.max(2, Math.min(24, slot - 4));
    return data.map((d, i) => {
      const x = padL + i * slot + (slot - barW) / 2;
      const h = max ? Math.max((d.value / max) * plotH, 1) : 1;
      const y = padT + plotH - h;
      return { x, y, w: barW, h, label: d.label, title: `${d.label}: ${formatValue(d.value)}` };
    });
  });
</script>

{#if !data.length}
  <div class="dv-empty">No data yet.</div>
{:else}
  <svg viewBox="0 0 {width} {height}" class="dv-chart">
    <line x1={padL} y1={padT + plotH} x2={width - padR} y2={padT + plotH} stroke="var(--border)" stroke-width="1" />
    {#each bars as b}
      <rect x={b.x} y={b.y} width={b.w} height={b.h} rx="3" fill="var(--accent)"><title>{b.title}</title></rect>
    {/each}
  </svg>
{/if}

<style>
  .dv-chart { display: block; width: 100%; height: auto; }
  .dv-empty { color: var(--muted); font-size: 0.8rem; text-align: center; padding: 1rem 0; }
</style>
