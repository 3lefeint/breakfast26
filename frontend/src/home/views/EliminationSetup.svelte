<script>
  // Mirrors index.html's #elimSetup: lives counter, reorderable game-player
  // list, known-player chips to add/remove, start button. Local-only state
  // (gamePlayers/livesCount) until Start is pressed, exactly like the
  // original vanilla-JS globals.
  import { players } from '../../lib/stores/players.js';
  import { api } from '../../lib/api.js';
  import { cap } from '../../lib/util.js';

  let gamePlayers = $state([]);
  let livesCount = $state(3);
  let randomOrder = $state(false);

  function toggle(name) {
    const idx = gamePlayers.indexOf(name);
    if (idx >= 0) gamePlayers.splice(idx, 1);
    else gamePlayers.push(name);
  }
  function removeFromGame(i) {
    gamePlayers.splice(i, 1);
  }
  function movePlayer(i, dir) {
    const j = i + dir;
    if (j < 0 || j >= gamePlayers.length) return;
    [gamePlayers[i], gamePlayers[j]] = [gamePlayers[j], gamePlayers[i]];
  }
  function changeLives(d) {
    livesCount = Math.max(1, Math.min(10, livesCount + d));
  }

  function shuffled(arr) {
    const result = arr.slice();
    for (let i = result.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [result[i], result[j]] = [result[j], result[i]];
    }
    return result;
  }

  async function start() {
    if (gamePlayers.length < 2) { alert('Select at least 2 players.'); return; }
    const order = randomOrder ? shuffled(gamePlayers) : gamePlayers;
    await api('POST', '/api/elimination/start', { players: order, lives: livesCount });
    window.location.href = '/tv';
  }
</script>

<div class="elim-section">
  <div class="elim-section-title">Setup</div>

  <div class="lives-row">
    <span class="label">Lives per player</span>
    <div class="counter">
      <button class="btn-counter" onclick={() => changeLives(-1)}>−</button>
      <span class="counter-val">{livesCount}</span>
      <button class="btn-counter" onclick={() => changeLives(+1)}>+</button>
    </div>
  </div>

  <div class="elim-columns">
    <div class="elim-column">
      <div class="elim-section-title">Known players <span class="hint">(click to add/remove)</span></div>
      <div class="known-chips">
        {#each $players.known as name (name)}
          <button type="button" class="chip" class:in-game={gamePlayers.includes(name)} onclick={() => toggle(name)}>{cap(name)}</button>
        {/each}
      </div>
    </div>

    <div class="elim-column">
      <div class="elim-section-title">Game players <span class="hint">(order = play order)</span></div>
      <ul class="game-players">
        {#each gamePlayers as name, i (name)}
          <li>
            <span class="player-name-text">{cap(name)}</span>
            <button class="btn-icon" onclick={() => movePlayer(i, -1)} disabled={i === 0}>↑</button>
            <button class="btn-icon" onclick={() => movePlayer(i, +1)} disabled={i === gamePlayers.length - 1}>↓</button>
            <button class="btn-icon remove" onclick={() => removeFromGame(i)}>×</button>
          </li>
        {/each}
      </ul>
    </div>
  </div>

  <label class="random-order-row">
    <input type="checkbox" bind:checked={randomOrder}>
    <span>Random order</span>
  </label>

  <button class="btn btn-start" onclick={start}>▶ Start</button>
</div>

<style>
  .elim-section {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 1.25rem; margin-bottom: 1rem;
  }
  .elim-section-title { font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 1rem; }
  .hint { color: var(--muted); font-size: 0.75rem; text-transform: none; letter-spacing: normal; }
  .lives-row { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 1rem; }
  .lives-row .label { font-size: 0.9rem; color: var(--muted); }
  .counter { display: flex; align-items: center; gap: 0.5rem; }
  .counter-val { font-size: 1.3rem; font-weight: 700; min-width: 2rem; text-align: center; }
  .btn-counter { background: var(--bg); border: 1px solid var(--border); color: var(--text); border-radius: 6px; width: 2rem; height: 2rem; cursor: pointer; font-size: 1.1rem; display: flex; align-items: center; justify-content: center; }
  .btn-counter:hover { border-color: var(--accent); }
  /* Known-players chips and the game-players list each get their own
     fixed column instead of stacking in one flow — otherwise every chip
     tap that grows the game-players list pushes the chip grid (and the
     very next chip you're about to tap) down by that same amount. Chips
     column comes first so it also reads naturally top-first when stacked
     on narrow viewports: pick from the pool, then see picks accumulate
     below, instead of the list's append point moving under your thumb.
     Each column also gets a *fixed* (not max-) height + its own scroll —
     a plain grid still stretches both columns' row to match whichever is
     tallest, so content below the grid (Random order/Start) would keep
     shifting with every tap right up until a max-height's ceiling was
     reached, which realistic player counts never hit. A fixed height
     from the very first item means the columns never resize at all,
     regardless of how many players are known or selected. */
  .elim-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 1.25rem; margin-bottom: 1rem; align-items: start; }
  .elim-column .elim-section-title { margin-bottom: 0.75rem; }
  @media (max-width: 640px) {
    .elim-columns { grid-template-columns: 1fr; gap: 1.5rem; }
  }
  .known-chips { display: flex; flex-wrap: wrap; gap: 0.4rem; align-content: flex-start; height: 260px; overflow-y: auto; }
  .chip {
    background: var(--bg); border: 1px solid var(--border); color: var(--text);
    border-radius: 20px; padding: 0.3rem 0.7rem; font-family: inherit;
    font-size: 0.85rem; cursor: pointer; transition: border-color 0.15s, color 0.15s;
  }
  .chip:hover { border-color: var(--accent); color: var(--accent); }
  .chip.in-game { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
  .game-players { list-style: none; margin-bottom: 1rem; padding: 0; height: 260px; overflow-y: auto; }
  .game-players li {
    display: flex; align-items: center; gap: 0.5rem;
    padding: 0.4rem 0; border-bottom: 1px solid var(--border);
  }
  .game-players li:last-child { border: none; }
  .player-name-text { flex: 1; font-size: 0.95rem; }
  .btn-icon { background: none; border: 1px solid var(--border); border-radius: 6px; color: var(--muted); cursor: pointer; padding: 0.2rem 0.45rem; font-size: 0.8rem; }
  .btn-icon:hover { border-color: var(--accent); color: var(--text); }
  .btn-icon.remove:hover { border-color: var(--red); color: var(--red); }
  .random-order-row { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 1rem; cursor: pointer; font-size: 0.9rem; color: var(--muted); }
  .random-order-row input { accent-color: var(--accent); }
  .btn { border: none; border-radius: 8px; padding: 0.65rem 1.5rem; font-size: 0.95rem; font-weight: 600; cursor: pointer; transition: opacity 0.15s; }
  .btn:hover { opacity: 0.85; }
  .btn:disabled { opacity: 0.4; cursor: default; }
  .btn-start { background: #166534; color: #fff; }
</style>
