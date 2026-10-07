<script>
  import { t } from '../../lib/i18n.js';
  // Random checkout setup: one player, the range of scores, the number of attempts and whether the
  // standard route is shown while throwing.
  import { players } from '../../lib/stores/players.js';
  import { cap } from '../../lib/util.js';
  import { RANGES, rangeLabel, startRun } from '../../lib/checkoutTraining.js';

  let player = $state(null);
  let rangeId = $state('all');
  let attempts = $state(10);
  let showRoute = $state(false);
  let range = $derived(RANGES.find((r) => r.id === rangeId));

  function changeAttempts(d) {
    attempts = Math.max(1, Math.min(100, attempts + d));
  }

  async function start() {
    if (!player) { alert(t('Select a player.')); return; }
    if (await startRun({ player, low: range.low, high: range.high, attempts, show_route: showRoute })) window.location.href = '/tv';
  }
</script>

<div class="section">
  <div class="section-title">{t('Setup')}</div>

  <div class="section-title sub">{t('Player')}</div>
  <div class="chips">
    {#each $players.known as name (name)}
      <button type="button" class="chip" class:in-game={player === name} onclick={() => (player = name)}>{cap(name)}</button>
    {/each}
  </div>

  <div class="section-title sub">{t('Scores')}</div>
  <div class="chips" role="radiogroup" aria-label={t('Scores')}>
    {#each RANGES as r (r.id)}
      <button type="button" class="chip" class:in-game={rangeId === r.id} onclick={() => (rangeId = r.id)}>{rangeLabel(r.low, r.high)}</button>
    {/each}
  </div>
  <div class="hint">{t('A score you can finish with three darts is drawn from this range. Finish it on a double, the bull\'s eye counts.')}</div>

  <div class="option-row">
    <span class="label">{t('Attempts')}</span>
    <div class="counter">
      <button class="btn-counter" onclick={() => changeAttempts(-5)}>−5</button>
      <button class="btn-counter" onclick={() => changeAttempts(-1)}>−</button>
      <span class="counter-val">{attempts}</span>
      <button class="btn-counter" onclick={() => changeAttempts(+1)}>+</button>
      <button class="btn-counter" onclick={() => changeAttempts(+5)}>+5</button>
    </div>
  </div>

  <label class="check">
    <input type="checkbox" bind:checked={showRoute} />
    <span>{t('Show the standard route while throwing')}</span>
  </label>

  <button class="btn btn-start" onclick={start}>{t('▶ Start')}</button>
</div>

<style>
  .section { background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); border-radius: 16px; padding: 1.25rem; margin-bottom: 1rem; }
  .section-title { font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 1rem; }
  .section-title.sub { margin: 1.25rem 0 0.6rem; }
  .hint { color: var(--muted); font-size: 0.8rem; margin: 0.6rem 0 1rem; }
  .chips { display: flex; flex-wrap: wrap; gap: 0.4rem; max-height: 220px; overflow-y: auto; }
  .chip { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 20px; padding: 0.3rem 0.7rem; font-family: inherit; font-size: 0.85rem; cursor: pointer; transition: border-color 0.15s, color 0.15s; }
  .chip:hover { border-color: var(--accent); color: var(--accent); }
  .chip.in-game { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
  .option-row { display: flex; align-items: center; gap: 0.75rem; margin: 1.25rem 0 0; flex-wrap: wrap; }
  .option-row .label { font-size: 0.9rem; color: var(--muted); min-width: 5rem; }
  .counter { display: flex; align-items: center; gap: 0.5rem; }
  .counter-val { font-size: 1.3rem; font-weight: 700; min-width: 3rem; text-align: center; }
  .btn-counter { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 10px; min-width: 2rem; height: 2rem; padding: 0 0.4rem; cursor: pointer; font-size: 0.95rem; display: flex; align-items: center; justify-content: center; }
  .btn-counter:hover { border-color: var(--accent); }
  .check { display: flex; align-items: center; gap: 0.6rem; margin: 1.25rem 0 1.25rem; font-size: 0.9rem; cursor: pointer; }
  .btn { border: none; border-radius: 8px; padding: 0.65rem 1.5rem; font-size: 0.95rem; font-weight: 600; cursor: pointer; transition: opacity 0.15s; }
  .btn:hover { opacity: 0.85; }
  .btn-start { background: #166534; color: #fff; }
</style>
