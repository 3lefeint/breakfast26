<script>
  // One ranking as thin horizontal bars, best first: the name on the left, the
  // bar scaled from zero to the best value, the value and its sample on the right.
  let { title, rows = [], large = false } = $props();

  let max = $derived(Math.max(0, ...rows.map((r) => r.value)));
</script>

<div class="card" class:large>
  <div class="title">{title}</div>
  {#if !rows.length}
    <div class="empty">No data yet.</div>
  {:else}
    <div class="rows">
    {#each rows as r (r.name)}
      <div class="row" title={r.tooltip}>
        <div class="name">{r.name}</div>
        <div class="track"><div class="bar" style:width="{max ? (r.value / max) * 100 : 0}%"></div></div>
        <div class="text"><span class="value">{r.text}</span>{#if r.sub}<span class="sub">{r.sub}</span>{/if}</div>
      </div>
    {/each}
    </div>
  {/if}
</div>

<style>
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 0.75rem 0.9rem; display: flex; flex-direction: column; }
  .rows { flex: 1; display: flex; flex-direction: column; justify-content: space-evenly; }
  .title { font-size: 0.75rem; color: var(--muted); margin-bottom: 0.6rem; }
  .empty { color: var(--muted); font-size: 0.8rem; text-align: center; padding: 0.8rem 0; }
  .row { display: grid; grid-template-columns: 4.8rem 1fr 5.6rem; align-items: center; gap: 0.6rem; padding: 0.2rem 0; }
  .name { font-size: 0.8rem; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .track { height: 0.85rem; }
  .bar { height: 100%; min-width: 2px; background: var(--accent); border-radius: 0 4px 4px 0; }
  .text { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .value { font-size: 0.8rem; font-weight: 700; }
  .sub { font-size: 0.65rem; color: var(--muted); margin-left: 0.3rem; }
  .large .row { grid-template-columns: 5.5rem 1fr 6.2rem; padding: 0.3rem 0; }
  .large .name { font-size: 0.95rem; }
  .large .track { height: 1.25rem; }
  .large .value { font-size: 0.95rem; }
  .large .sub { font-size: 0.72rem; }
</style>
