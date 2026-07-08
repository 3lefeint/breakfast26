<script>
  // Mirrors index.html's .elim-darts markup: 3 dart boxes + a running total.
  // darts: array of 0-3 numbers (thrown darts so far this turn).
  let { darts = [] } = $props();
  let total = $derived(darts.reduce((a, b) => a + b, 0));
</script>

<div class="elim-darts">
  {#each [0, 1, 2] as i}
    <div class="dart-box">
      <div class="label">D{i + 1}</div>
      <div class="value">{darts[i] ?? '—'}</div>
    </div>
  {/each}
  <div class="turn-total">
    <div class="label">Total</div>
    <div class="value">{total}</div>
  </div>
</div>

<style>
  .elim-darts { display: grid; grid-template-columns: 1fr 1fr 1fr auto; gap: 0.5rem; margin-bottom: 1rem; }
  .dart-box {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 0.5rem 0.75rem;
    text-align: center;
  }
  .dart-box .label { font-size: 0.7rem; color: var(--muted); margin-bottom: 2px; }
  .dart-box .value { font-size: 1.3rem; font-weight: 700; }
  .turn-total { text-align: right; }
  .turn-total .label { font-size: 0.7rem; color: var(--muted); }
  .turn-total .value { font-size: 1.5rem; font-weight: 700; color: var(--yellow); }
</style>
