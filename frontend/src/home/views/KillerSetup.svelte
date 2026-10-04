<script>
  // Killer setup: players (order = play order, or random) and the two options. Every player gets a
  // random number when the game starts. Local state until Start is pressed.
  import { players } from '../../lib/stores/players.js';
  import { apiJson } from '../../lib/api.js';
  import { cap } from '../../lib/util.js';

  const MAX_PLAYERS = 20;

  let gamePlayers = $state([]);
  let ownGoal = $state(false);
  let singles = $state(false);
  let bullOff = $state(true);
  let throwNumbers = $state(true);
  let randomOrder = $state(false);

  function toggle(name) {
    const idx = gamePlayers.indexOf(name);
    if (idx >= 0) gamePlayers.splice(idx, 1);
    else if (gamePlayers.length < MAX_PLAYERS) gamePlayers.push(name);
  }
  function removeFromGame(i) { gamePlayers.splice(i, 1); }
  function movePlayer(i, dir) {
    const j = i + dir;
    if (j < 0 || j >= gamePlayers.length) return;
    [gamePlayers[i], gamePlayers[j]] = [gamePlayers[j], gamePlayers[i]];
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
    const res = await apiJson('POST', '/api/killer/start', {
      players: order, own_goal: ownGoal, singles, bull_off: bullOff, throw_numbers: throwNumbers,
    });
    if (res.error) { alert(res.error); return; }
    window.location.href = '/tv';
  }
</script>

<div class="section">
  <div class="section-title">Setup</div>

  <p class="rules">
    Everyone gets a number and three lives. A double on your own number makes you a killer,
    from then on you take one life from an opponent with every double on their number. Last one standing wins.
  </p>

  <label class="check-row">
    <input type="checkbox" bind:checked={bullOff}>
    <span>Bull-off: everybody throws one dart at the bull, the closest one starts</span>
  </label>
  <label class="check-row">
    <input type="checkbox" bind:checked={throwNumbers}>
    <span>Throw for the numbers: everybody throws one dart with the other hand and gets the number it hits (a double makes a killer at once). Off: the numbers are drawn at random</span>
  </label>

  <label class="check-row">
    <input type="checkbox" bind:checked={singles}>
    <span>Singles take lives too, not only doubles (triples never do)</span>
  </label>
  <label class="check-row">
    <input type="checkbox" bind:checked={ownGoal}>
    <span>Own goal: a killer who hits their own number loses a life</span>
  </label>

  <div class="columns">
    <div class="column">
      <div class="section-title">Known players <span class="hint">(click to add/remove)</span></div>
      <div class="known-chips">
        {#each $players.known as name (name)}
          <button type="button" class="chip" class:in-game={gamePlayers.includes(name)} onclick={() => toggle(name)}>{cap(name)}</button>
        {/each}
      </div>
    </div>

    <div class="column">
      <div class="section-title">Game players <span class="hint">(order = play order, 2 to {MAX_PLAYERS})</span></div>
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

  <label class="check-row">
    <input type="checkbox" bind:checked={randomOrder}>
    <span>Random order</span>
  </label>

  <button class="btn btn-start" onclick={start}>▶ Start</button>
</div>

<style>
  .rules { color: var(--muted); font-size: 0.9rem; margin-bottom: 1rem; line-height: 1.45; }
  .section { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1.25rem; margin-bottom: 1rem; }
  .section-title { font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 1rem; }
  .hint { color: var(--muted); font-size: 0.75rem; text-transform: none; letter-spacing: normal; }
  .option-row { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 1rem; flex-wrap: wrap; }
  .option-row .label { font-size: 0.9rem; color: var(--muted); min-width: 5rem; }
  .counter { display: flex; align-items: center; gap: 0.5rem; }
  .counter-val { font-size: 1.3rem; font-weight: 700; min-width: 2rem; text-align: center; }
  .btn-counter { background: var(--bg); border: 1px solid var(--border); color: var(--text); border-radius: 6px; width: 2rem; height: 2rem; cursor: pointer; font-size: 1.1rem; display: flex; align-items: center; justify-content: center; }
  .btn-counter:hover { border-color: var(--accent); }
  .seg { display: flex; gap: 0.4rem; }
  .seg-btn { background: var(--bg); border: 1px solid var(--border); color: var(--muted); border-radius: 20px; padding: 0.3rem 0.9rem; font-family: inherit; font-size: 0.85rem; cursor: pointer; }
  .seg-btn:hover { border-color: var(--accent); color: var(--text); }
  .seg-btn.active { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); font-weight: 700; }
  .targets { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; margin: -0.25rem 0 1rem 5.75rem; }
  .target-cell { display: flex; flex-direction: column; align-items: center; gap: 0.15rem; font-size: 0.7rem; color: var(--muted); }
  .target-cell input { width: 3.2rem; background: var(--bg); border: 1px solid var(--border); border-radius: 6px; color: var(--text); padding: 0.25rem; text-align: center; font-family: inherit; }
  select { background: var(--bg); border: 1px solid var(--border); border-radius: 6px; color: var(--text); padding: 0.35rem 0.5rem; font-family: inherit; }
  .check-row { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 1rem; cursor: pointer; font-size: 0.9rem; color: var(--muted); }
  .check-row input { accent-color: var(--accent); }
  .columns { display: grid; grid-template-columns: 1fr 1fr; gap: 1.25rem; margin: 1.5rem 0 1rem; align-items: start; }
  .column .section-title { margin-bottom: 0.75rem; }
  @media (max-width: 640px) { .columns { grid-template-columns: 1fr; gap: 1.5rem; } .targets { margin-left: 0; } }
  .known-chips { display: flex; flex-wrap: wrap; gap: 0.4rem; align-content: flex-start; height: 220px; overflow-y: auto; }
  .chip { background: var(--bg); border: 1px solid var(--border); color: var(--text); border-radius: 20px; padding: 0.3rem 0.7rem; font-family: inherit; font-size: 0.85rem; cursor: pointer; transition: border-color 0.15s, color 0.15s; }
  .chip:hover { border-color: var(--accent); color: var(--accent); }
  .chip.in-game { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
  .game-players { list-style: none; margin-bottom: 1rem; padding: 0; height: 220px; overflow-y: auto; }
  .game-players li { display: flex; align-items: center; gap: 0.5rem; padding: 0.4rem 0; border-bottom: 1px solid var(--border); }
  .game-players li:last-child { border: none; }
  .player-name-text { flex: 1; font-size: 0.95rem; }
  .btn-icon { background: none; border: 1px solid var(--border); border-radius: 6px; color: var(--muted); cursor: pointer; padding: 0.2rem 0.45rem; font-size: 0.8rem; }
  .btn-icon:hover { border-color: var(--accent); color: var(--text); }
  .btn-icon.remove:hover { border-color: var(--red); color: var(--red); }
  .btn { border: none; border-radius: 8px; padding: 0.65rem 1.5rem; font-size: 0.95rem; font-weight: 600; cursor: pointer; transition: opacity 0.15s; }
  .btn:hover { opacity: 0.85; }
  .btn-start { background: #166534; color: #fff; }
</style>
