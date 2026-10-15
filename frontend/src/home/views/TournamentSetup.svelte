<script>
  import { t } from '../../lib/i18n.js';
  // Tournament setup: the rules (base score, in and out mode, who throws first, legs to win per round), the
  // players, and the bracket itself. The players are drawn into the bracket as soon as there are two; a draw
  // is random, byes included. Two seats are swapped by clicking one and then the other, a bye is a seat
  // like any. Local state until Start is pressed.
  import { players } from '../../lib/stores/players.js';
  import { apiJson } from '../../lib/api.js';
  import { cap } from '../../lib/util.js';
  import { START_SCORES, MODES, MAX_LEGS } from '../../lib/x01.js';
  import { roundName, roundsFor, previewSnap, drawSeats, startTournament } from '../../lib/tournament.js';
  import TournamentBracket from '../../lib/components/TournamentBracket.svelte';

  let gamePlayers = $state([]);
  let newName = $state('');
  let startScore = $state(501);
  let inMode = $state('straight');
  let outMode = $state('double');
  let bullOff = $state(true);
  let legsByRound = $state([1]);
  let seats = $state(null);
  let picked = $state(null);

  const MODE_LABEL = { straight: () => t('Straight'), double: () => t('Double'), master: () => t('Master') };

  let rounds = $derived(roundsFor(Math.max(2, gamePlayers.length)));
  $effect(() => {
    if (legsByRound.length !== rounds) {
      legsByRound = Array.from({ length: rounds }, (_, i) => legsByRound[i] ?? 1);
    }
  });

  // Every change of the players draws the bracket again.
  async function redraw() {
    picked = null;
    if (gamePlayers.length < 2) { seats = null; return; }
    const result = await drawSeats(gamePlayers);
    if (result) seats = result;
  }

  function toggle(name) {
    const idx = gamePlayers.indexOf(name);
    if (idx >= 0) gamePlayers.splice(idx, 1);
    else gamePlayers.push(name);
    redraw();
  }
  function removeFromGame(i) { gamePlayers.splice(i, 1); redraw(); }

  async function addPlayer() {
    const name = newName.trim();
    if (!name) return;
    const res = await apiJson('POST', '/api/players', { name });
    if (res.error) { alert(t(res.error)); return; }
    newName = '';
    if (!gamePlayers.includes(name)) { gamePlayers.push(name); redraw(); }
  }

  function setScore(e) {
    const n = parseInt(e.target.value, 10);
    if (Number.isFinite(n)) startScore = Math.max(2, Math.min(1501, n));
  }

  // Click a seat, then another one: they swap places.
  function pick(i) {
    if (picked == null) { picked = i; return; }
    if (picked !== i) [seats[picked], seats[i]] = [seats[i], seats[picked]];
    picked = null;
  }

  let preview = $derived(seats ? previewSnap(seats, legsByRound) : null);
  let valid = $derived(!!seats && seats.every((_, i) => i % 2 || seats[i] || seats[i + 1]));

  async function start() {
    if (!valid) return;
    const ok = await startTournament({
      seats, start: startScore, in_mode: inMode, out_mode: outMode, bull_off: bullOff, legs_by_round: legsByRound,
    });
    if (ok) window.location.href = '/tv';
  }
</script>

<div class="section">
  <div class="top">
    <div class="left">
      <div class="option-row">
        <span class="label">{t('Base Score')}</span>
        <div class="seg">
          {#each START_SCORES as s (s)}
            <button type="button" class="seg-btn" class:active={startScore === s} onclick={() => (startScore = s)}>{s}</button>
          {/each}
          <input class="score-input" type="number" min="2" max="1501" value={startScore} onchange={setScore}>
        </div>
      </div>

      <div class="option-row">
        <span class="label">{t('In Mode')}</span>
        <div class="seg">
          {#each MODES as m (m)}
            <button type="button" class="seg-btn" class:active={inMode === m} onclick={() => (inMode = m)}>{MODE_LABEL[m]()}</button>
          {/each}
        </div>
      </div>

      <div class="option-row">
        <span class="label">{t('Out Mode')}</span>
        <div class="seg">
          {#each MODES as m (m)}
            <button type="button" class="seg-btn" class:active={outMode === m} onclick={() => (outMode = m)}>{MODE_LABEL[m]()}</button>
          {/each}
        </div>
      </div>

      <div class="option-row">
        <span class="label">{t('Bull-Off')}</span>
        <label class="switch">
          <input type="checkbox" bind:checked={bullOff}>
          <span class="slider"></span>
        </label>
      </div>

      <div class="section-title">{t('Choose Players')}</div>
      <div class="known-chips">
        {#each $players.known as name (name)}
          <button type="button" class="chip" class:in-game={gamePlayers.includes(name)} onclick={() => toggle(name)}>{cap(name)}</button>
        {/each}
      </div>
      <div class="add-row">
        <input class="text-input" placeholder={t('New player')} bind:value={newName} onkeydown={(e) => e.key === 'Enter' && addPlayer()}>
        <button class="btn-small" onclick={addPlayer}>{t('Add player')}</button>
      </div>
    </div>

    <!-- The same word in both languages; t('Players') is taken by the navigation. -->
    <div class="right">
      <div class="section-title">Players</div>
      <ul class="game-players">
        {#each gamePlayers as name, i (name)}
          <li>
            <span class="player-name-text">{cap(name)}</span>
            <button class="btn-icon remove" onclick={() => removeFromGame(i)}>×</button>
          </li>
        {/each}
      </ul>
    </div>
  </div>

  <div class="section-title legs-title">{t('Legs per round')}</div>
  <div class="legs">
    {#each legsByRound as n, r (r)}
      <div class="leg-item">
        <span class="label">{roundName(r, rounds)}</span>
        <div class="counter">
          <button class="btn-counter" onclick={() => (legsByRound[r] = Math.max(1, n - 1))}>−</button>
          <span class="counter-val">{n}</span>
          <button class="btn-counter" onclick={() => (legsByRound[r] = Math.min(MAX_LEGS, n + 1))}>+</button>
        </div>
      </div>
    {/each}
  </div>

  {#if preview}
    <div class="section-title">{t('Click two seats to swap them')}</div>
    <TournamentBracket snap={preview} editable {picked} onSeat={pick} />
    {#if !valid}<p class="warn">{t('A bye cannot face a bye.')}</p>{/if}
  {/if}

  <div class="actions">
    <button class="btn ghost" disabled={gamePlayers.length < 2} onclick={redraw}>{t('Redraw')}</button>
    <button class="btn btn-start" disabled={!valid} onclick={start}>{t('▶ Start')}</button>
  </div>
</div>

<style>
  .section { background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); border-radius: 16px; padding: 1.25rem; margin-bottom: 1rem; }
  .section-title { font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 1rem; }
  .legs-title { margin-top: 1.2rem; }
  .hint { color: var(--muted); font-size: 0.75rem; text-transform: none; letter-spacing: normal; }
  /* The left column has a fixed height, the list of players on the right fills it and scrolls: nothing moves
     when players are added. */
  .top { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 1.5rem; align-items: stretch; margin-bottom: 1.2rem; }
  .right { display: flex; flex-direction: column; min-height: 0; }
  .right .section-title { margin-bottom: 0.5rem; }
  @media (max-width: 900px) { .top { grid-template-columns: 1fr; } .game-players { max-height: 14rem; flex: none; } }
  .option-row { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.8rem; flex-wrap: wrap; }
  .option-row .label { font-size: 0.9rem; color: var(--muted); min-width: 8rem; }
  .legs { display: flex; flex-wrap: wrap; gap: 0.6rem 1.8rem; margin-bottom: 1.2rem; }
  .leg-item { display: flex; align-items: center; gap: 0.6rem; }
  .leg-item .label { font-size: 0.9rem; color: var(--muted); }
  .counter { display: flex; align-items: center; gap: 0.5rem; }
  .counter-val { font-size: 1.15rem; font-weight: 700; min-width: 1.4rem; text-align: center; }
  .btn-counter { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 8px; width: 1.5rem; height: 1.5rem; cursor: pointer; font-size: 0.95rem; line-height: 1; display: flex; align-items: center; justify-content: center; }
  .btn-counter:hover { border-color: var(--accent); }
  .switch { position: relative; display: inline-block; width: 2.8rem; height: 1.5rem; cursor: pointer; }
  .switch input { opacity: 0; width: 0; height: 0; }
  .slider { position: absolute; inset: 0; border-radius: 999px; background: var(--glass); border: 1px solid var(--glass-border); transition: background 0.15s, border-color 0.15s; }
  .slider::before { content: ''; position: absolute; width: 1.05rem; height: 1.05rem; left: 0.2rem; top: 50%; transform: translateY(-50%); border-radius: 50%; background: var(--muted); transition: transform 0.15s, background 0.15s; }
  .switch input:checked + .slider { background: var(--accent-soft); border-color: var(--accent); }
  .switch input:checked + .slider::before { transform: translate(1.3rem, -50%); background: var(--accent); }
  .switch input:focus-visible + .slider { outline: 2px solid var(--accent); outline-offset: 2px; }
  .seg { display: flex; gap: 0.4rem; flex-wrap: wrap; align-items: center; }
  .seg-btn { background: var(--glass); border: 1px solid var(--glass-border); color: var(--muted); border-radius: 20px; padding: 0.3rem 0.9rem; font-family: inherit; font-size: 0.85rem; cursor: pointer; }
  .seg-btn:hover { border-color: var(--accent); color: var(--text); }
  .seg-btn.active { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); font-weight: 700; }
  .score-input, .text-input { background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 12px; color: var(--text); padding: 0.3rem 0.6rem; font-family: inherit; }
  .score-input { width: 5rem; text-align: center; }
  .text-input { flex: 1; min-width: 0; }
  @media (max-width: 640px) { .option-row .label { min-width: 0; width: 100%; } }
  .known-chips { display: flex; flex-wrap: wrap; gap: 0.4rem; align-content: flex-start; height: 8.5rem; overflow-y: auto; margin-bottom: 0.8rem; }
  .chip { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 20px; padding: 0.3rem 0.7rem; font-family: inherit; font-size: 0.85rem; cursor: pointer; transition: border-color 0.15s, color 0.15s; }
  .chip:hover { border-color: var(--accent); color: var(--accent); }
  .chip.in-game { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
  .add-row { display: flex; gap: 0.5rem; max-width: 34rem; }
  .btn-small { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 12px; padding: 0.3rem 0.9rem; font-family: inherit; cursor: pointer; }
  .btn-small:hover { border-color: var(--accent); }
  .game-players { list-style: none; margin: 0; padding: 0; flex: 1 1 0; min-height: 0; overflow-y: auto; }
  .game-players li { display: flex; align-items: center; gap: 0.5rem; padding: 0.4rem 0; border-bottom: 1px solid var(--glass-border); }
  .game-players li:last-child { border: none; }
  .player-name-text { flex: 1; font-size: 0.95rem; }
  .btn-icon { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 6px; color: var(--muted); cursor: pointer; padding: 0.2rem 0.45rem; font-size: 0.8rem; }
  .btn-icon.remove:hover { border-color: var(--red); color: var(--red); }
  .warn { color: var(--red); font-size: 0.85rem; margin: 0.5rem 0 0; }
  .actions { display: flex; gap: 0.6rem; flex-wrap: wrap; margin-top: 1rem; }
  .btn { border: none; border-radius: 8px; padding: 0.65rem 1.5rem; font-size: 0.95rem; font-weight: 600; cursor: pointer; transition: opacity 0.15s; }
  .btn:hover:not(:disabled) { opacity: 0.85; }
  .btn:disabled { opacity: 0.4; cursor: default; }
  .btn-start { background: #166534; color: #fff; }
  .btn.ghost { background: var(--glass); color: color-mix(in srgb, var(--text) 82%, transparent); border: 1px solid var(--glass-border); }
</style>
