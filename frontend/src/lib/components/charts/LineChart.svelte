<script>
  // Ports index.html's lineChartSVG().
  let { data = [], formatValue = (v) => v } = $props();

  const width = 480, height = 130, padL = 4, padR = 46, padT = 12, padB = 18;
  const plotW = width - padL - padR, plotH = height - padT - padB;

  let chart = $derived.by(() => {
    const values = data.map((d) => d.value);
    const max = Math.max(...values, 1), min = Math.min(...values, 0);
    const span = (max - min) || 1;
    const n = data.length;
    const x = (i) => padL + (n <= 1 ? plotW / 2 : (i / (n - 1)) * plotW);
    const y = (v) => padT + plotH - ((v - min) / span) * plotH;
    const points = data.map((d, i) => `${x(i).toFixed(1)},${y(d.value).toFixed(1)}`).join(' ');
    const dots = data.map((d, i) => ({ cx: x(i), cy: y(d.value), title: `${d.label}: ${formatValue(d.value)}` }));
    const last = data[n - 1];
    const endLabel = last ? { x: x(n - 1) + 7, y: y(last.value) + 4, text: String(formatValue(last.value)) } : null;
    return { points, dots, endLabel };
  });
</script>

{#if !data.length}
  <div class="dv-empty">No data yet.</div>
{:else}
  <svg viewBox="0 0 {width} {height}" class="dv-chart">
    <line x1={padL} y1={padT + plotH} x2={width - padR} y2={padT + plotH} stroke="var(--border)" stroke-width="1" />
    <polyline points={chart.points} fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
    {#each chart.dots as d}
      <circle cx={d.cx} cy={d.cy} r="3" fill="var(--accent)"><title>{d.title}</title></circle>
    {/each}
    {#if chart.endLabel}
      <text x={chart.endLabel.x} y={chart.endLabel.y} font-size="11" fill="var(--text)">{chart.endLabel.text}</text>
    {/if}
  </svg>
{/if}

<style>
  .dv-chart { display: block; width: 100%; height: auto; }
  .dv-empty { color: var(--muted); font-size: 0.8rem; text-align: center; padding: 1rem 0; }
</style>
