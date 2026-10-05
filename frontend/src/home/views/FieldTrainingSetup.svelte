<script>
  // Field Training setup: one player, the field (a number or the bull) and the number of darts.
  // The darts follow the field until they are changed: 100 at a number, 50 at the bull. A run
  // with fewer darts than that is saved as practice.
  import { players } from '../../lib/stores/players.js';
  import { cap } from '../../lib/util.js';
  import { BULL, fieldLabel, standardDarts, startRun } from '../../lib/fieldTraining.js';

  let player = $state(null);
  let field = $state(20);
  let customDarts = $state(null);   // null: the standard number for the field
  let darts = $derived(customDarts ?? standardDarts(field));
  let practice = $derived(darts < standardDarts(field));

  function changeDarts(d) {
    customDarts = Math.max(1, Math.min(999, darts + d));
  }

  async function start() {
    if (!player) { alert('Select a player.'); return; }
    if (!Number.isInteger(darts) || darts < 1) { alert('The number of darts has to be at least 1.'); return; }
    if (await startRun({ player, field, darts })) window.location.href = '/tv';
  }
</script>

<div class="section">
  <div class="section-title">Setup</div>

  <div class="section-title sub">Player</div>
  <div class="chips">
    {#each $players.known as name (name)}
      <button type="button" class="chip" class:in-game={player === name} onclick={() => (player = name)}>{cap(name)}</button>
    {/each}
  </div>

  <div class="section-title sub">Field</div>
  <div class="fields" role="radiogroup" aria-label="Field">
    {#each Array.from({ length: 20 }, (_, i) => i + 1) as n}
      <button type="button" class="field" class:active={field === n} onclick={() => (field = n)}>{n}</button>
    {/each}
    <button type="button" class="field bull" class:active={field === BULL} onclick={() => (field = BULL)}>Bull</button>
  </div>
  <div class="hint">
    {#if field === BULL}Outer bull 1 point, bull's eye 2 points.{:else}Single 1 point, double 2 points, triple 3 points.{/if}
    Everything else scores 0.
  </div>

  <div class="option-row">
    <span class="label">Darts</span>
    <div class="counter">
      <button class="btn-counter" onclick={() => changeDarts(-10)}>−10</button>
      <button class="btn-counter" onclick={() => changeDarts(-1)}>−</button>
      <span class="counter-val">{darts}</span>
      <button class="btn-counter" onclick={() => changeDarts(+1)}>+</button>
      <button class="btn-counter" onclick={() => changeDarts(+10)}>+10</button>
    </div>
  </div>
  <div class="hint">
    {#if practice}
      Fewer than {standardDarts(field)} darts at {fieldLabel(field)}: the run is saved as practice, without a rating or a personal best.
    {:else}
      From {standardDarts(field)} darts at {fieldLabel(field)} on a complete run counts for the rating and the personal best.
    {/if}
  </div>

  <button class="btn btn-start" onclick={start}>▶ Start</button>
</div>

<style>
  .section { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1.25rem; margin-bottom: 1rem; }
  .section-title { font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 1rem; }
  .section-title.sub { margin: 1.25rem 0 0.6rem; }
  .hint { color: var(--muted); font-size: 0.8rem; margin: 0.6rem 0 1rem; }
  .chips { display: flex; flex-wrap: wrap; gap: 0.4rem; max-height: 220px; overflow-y: auto; }
  .chip { background: var(--bg); border: 1px solid var(--border); color: var(--text); border-radius: 20px; padding: 0.3rem 0.7rem; font-family: inherit; font-size: 0.85rem; cursor: pointer; transition: border-color 0.15s, color 0.15s; }
  .chip:hover { border-color: var(--accent); color: var(--accent); }
  .chip.in-game { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
  .fields { display: grid; grid-template-columns: repeat(7, 1fr); gap: 0.4rem; }
  .field { background: var(--bg); border: 1px solid var(--border); color: var(--text); border-radius: 8px; padding: 0.5rem 0; font-family: inherit; font-size: 0.95rem; font-weight: 600; cursor: pointer; }
  .field:hover { border-color: var(--accent); }
  .field.active { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); font-weight: 800; }
  .field.bull { grid-column: span 2; }
  .option-row { display: flex; align-items: center; gap: 0.75rem; margin: 1.25rem 0 0; flex-wrap: wrap; }
  .option-row .label { font-size: 0.9rem; color: var(--muted); min-width: 5rem; }
  .counter { display: flex; align-items: center; gap: 0.5rem; }
  .counter-val { font-size: 1.3rem; font-weight: 700; min-width: 3rem; text-align: center; }
  .btn-counter { background: var(--bg); border: 1px solid var(--border); color: var(--text); border-radius: 6px; min-width: 2rem; height: 2rem; padding: 0 0.4rem; cursor: pointer; font-size: 0.95rem; display: flex; align-items: center; justify-content: center; }
  .btn-counter:hover { border-color: var(--accent); }
  .btn { border: none; border-radius: 8px; padding: 0.65rem 1.5rem; font-size: 0.95rem; font-weight: 600; cursor: pointer; transition: opacity 0.15s; }
  .btn:hover { opacity: 0.85; }
  .btn-start { background: #166534; color: #fff; }
</style>
