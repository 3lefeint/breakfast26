<script>
  // Black Belt setup: one player and the direction of the ladder. There is no limit, a run ends
  // with the belt or when it is finished.
  import { players } from '../../lib/stores/players.js';
  import { cap } from '../../lib/util.js';
  import { startRun } from '../../lib/blackBelt.js';

  let player = $state(null);
  let backwards = $state(false);

  async function start() {
    if (!player) { alert('Select a player.'); return; }
    if (await startRun({ player, backwards })) window.location.href = '/tv';
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

  <div class="section-title sub">Ladder</div>
  <div class="seg" role="radiogroup" aria-label="Direction">
    <button type="button" class="seg-btn" class:active={!backwards} onclick={() => (backwards = false)}>D1 up to D20</button>
    <button type="button" class="seg-btn" class:active={backwards} onclick={() => (backwards = true)}>D20 down to D1</button>
  </div>
  <div class="hint">
    Hit the double of every field in order, the bull's eye comes last. Each field has three darts of its own;
    the darts left in your hand after a hit are bonus darts at the next field. Miss a field with them and the
    ladder starts again. A run has no limit: it ends with the belt, or when you finish it.
  </div>

  <button class="btn btn-start" onclick={start}>▶ Start</button>
</div>

<style>
  .section { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1.25rem; margin-bottom: 1rem; }
  .section-title { font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 1rem; }
  .section-title.sub { margin: 1.25rem 0 0.6rem; }
  .hint { color: var(--muted); font-size: 0.8rem; margin: 0.8rem 0 1.25rem; max-width: 40rem; }
  .chips { display: flex; flex-wrap: wrap; gap: 0.4rem; max-height: 220px; overflow-y: auto; }
  .chip { background: var(--bg); border: 1px solid var(--border); color: var(--text); border-radius: 20px; padding: 0.3rem 0.7rem; font-family: inherit; font-size: 0.85rem; cursor: pointer; transition: border-color 0.15s, color 0.15s; }
  .chip:hover { border-color: var(--accent); color: var(--accent); }
  .chip.in-game { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
  .seg { display: flex; gap: 0.4rem; }
  .seg-btn { background: var(--bg); border: 1px solid var(--border); color: var(--muted); border-radius: 20px; padding: 0.3rem 0.9rem; font-family: inherit; font-size: 0.85rem; cursor: pointer; }
  .seg-btn:hover { border-color: var(--accent); color: var(--text); }
  .seg-btn.active { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); font-weight: 700; }
  .btn { border: none; border-radius: 8px; padding: 0.65rem 1.5rem; font-size: 0.95rem; font-weight: 600; cursor: pointer; transition: opacity 0.15s; }
  .btn:hover { opacity: 0.85; }
  .btn-start { background: #166534; color: #fff; }
</style>
