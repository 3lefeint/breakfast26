<script>
  // Mirrors index.html's #elimFinished + #rematchModal. Default rematch
  // order: first-eliminated player starts first, winner starts last
  // (elimination_order is already in that sequence — winner just gets
  // appended). Newly typed players are inserted as a contiguous block at
  // the front, in the order they were added, ahead of everyone carried
  // over from the last game.
  import { elimination } from '../../lib/stores/elimination.js';
  import { players } from '../../lib/stores/players.js';
  import { online } from '../../lib/stores/online.js';
  import { api, apiJson } from '../../lib/api.js';
  import { cap } from '../../lib/util.js';
  import ConfettiBurst from '../../lib/components/ConfettiBurst.svelte';

  let showModal = $state(false);
  let rematchPlayers = $state([]);
  let rematchNewInsertIdx = $state(0);
  let rematchLives = $state(3);
  let newPlayerName = $state('');

  function openRematchModal() {
    const e = $elimination;
    if (!e) return;
    rematchPlayers = [...(e.elimination_order || []), e.winner].filter(Boolean);
    rematchNewInsertIdx = 0;
    rematchLives = e.lives_max || 3;
    showModal = true;
  }
  function closeRematchModal() { showModal = false; }

  function toggleRematchPlayer(name) {
    const idx = rematchPlayers.indexOf(name);
    if (idx >= 0) {
      rematchPlayers.splice(idx, 1);
      if (idx < rematchNewInsertIdx) rematchNewInsertIdx--;
    } else {
      rematchPlayers.push(name);
    }
  }
  function removeFromRematch(i) {
    rematchPlayers.splice(i, 1);
    if (i < rematchNewInsertIdx) rematchNewInsertIdx--;
  }
  function moveRematchPlayer(i, dir) {
    const j = i + dir;
    if (j < 0 || j >= rematchPlayers.length) return;
    [rematchPlayers[i], rematchPlayers[j]] = [rematchPlayers[j], rematchPlayers[i]];
  }
  function changeRematchLives(d) {
    rematchLives = Math.max(1, Math.min(10, rematchLives + d));
  }

  async function addNewRematchPlayer() {
    const name = newPlayerName.trim();
    if (!name) return;
    if (!$players.known.includes(name)) {
      await api('POST', '/api/players', { name });
    }
    const existingIdx = rematchPlayers.indexOf(name);
    if (existingIdx >= 0) {
      rematchPlayers.splice(existingIdx, 1);
      if (existingIdx < rematchNewInsertIdx) rematchNewInsertIdx--;
    }
    rematchPlayers.splice(rematchNewInsertIdx, 0, name);
    rematchNewInsertIdx++;
    newPlayerName = '';
  }

  async function startRematch() {
    if (rematchPlayers.length < 2) { alert('Select at least 2 players.'); return; }
    await api('POST', '/api/elimination/start', { players: rematchPlayers, lives: rematchLives });
    window.location.href = '/tv';
  }

  async function newGame() {
    // Clear the finished game server-side too, not just the local form —
    // otherwise it stays "finished" forever and keeps showing the
    // winner/rematch screen until a new game actually starts.
    await api('POST', '/api/elimination/stop');
  }

  let onlineError = $state('');
  async function onlineRematch() {
    const res = await apiJson('POST', '/api/online/rematch');
    onlineError = res.error || '';
  }

  async function undoWin() {
    // Resumes the match server-side and un-records the win from
    // stats.db — for a match-ending dart that turned out to be
    // misdetected. Elimination.svelte's own $effect redirects to /tv
    // once state flips back to "playing".
    if (!confirm('Undo the winning turn and resume the match?')) return;
    await api('POST', '/api/elimination/undo');
  }
</script>

<ConfettiBurst />

<div class="elim-section finished">
  <div class="trophy">🏆</div>
  <div class="winner-name">{cap($elimination?.winner || '')}</div>
  <div class="winner-label">Winner</div>
  <div class="finished-actions">
    <button class="btn btn-start" onclick={newGame}>New game</button>
    {#if !$online}
      <button class="btn btn-add" onclick={openRematchModal}>🔁 Rematch</button>
    {:else if $online.host}
      <button class="btn btn-add" onclick={onlineRematch}>🔁 Rematch</button>
    {/if}
  </div>
  {#if $online && !$online.host}<p class="online-note">Only the host can start a rematch.</p>{/if}
  {#if onlineError}<p class="online-error">{onlineError}</p>{/if}
  {#if !$online}<button class="btn-undo-win" onclick={undoWin}>↩ Undo winning turn</button>{/if}
</div>

{#if showModal}
  <div class="modal-overlay">
    <button type="button" class="overlay-backdrop" aria-label="Close" onclick={closeRematchModal}></button>
    <div class="modal-box">
      <div class="elim-section-title">Rematch</div>

      <div class="lives-row">
        <span class="label">Lives per player</span>
        <div class="counter">
          <button class="btn-counter" onclick={() => changeRematchLives(-1)}>−</button>
          <span class="counter-val">{rematchLives}</span>
          <button class="btn-counter" onclick={() => changeRematchLives(+1)}>+</button>
        </div>
      </div>

      <div class="elim-section-title">Players <span class="hint">(first loser starts first, winner last)</span></div>
      <ul class="game-players">
        {#each rematchPlayers as name, i (name + i)}
          <li>
            <span class="player-name-text">{cap(name)}</span>
            <button class="btn-icon" onclick={() => moveRematchPlayer(i, -1)} disabled={i === 0}>↑</button>
            <button class="btn-icon" onclick={() => moveRematchPlayer(i, +1)} disabled={i === rematchPlayers.length - 1}>↓</button>
            <button class="btn-icon remove" onclick={() => removeFromRematch(i)}>×</button>
          </li>
        {/each}
      </ul>

      <div class="add-row">
        <input type="text" placeholder="Add new player (starts first)" bind:value={newPlayerName}
               onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addNewRematchPlayer(); } }}>
        <button class="btn btn-add" onclick={addNewRematchPlayer}>+ Add</button>
      </div>

      <div class="elim-section-title">Known players <span class="hint">(click to add/remove)</span></div>
      <div class="known-chips">
        {#each $players.known as name (name)}
          <button type="button" class="chip" class:in-game={rematchPlayers.includes(name)} onclick={() => toggleRematchPlayer(name)}>{cap(name)}</button>
        {/each}
      </div>

      <div class="modal-actions">
        <button class="btn btn-add" onclick={closeRematchModal}>Cancel</button>
        <button class="btn btn-start" onclick={startRematch}>▶ Start rematch</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .elim-section {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 1.25rem; margin-bottom: 1rem;
  }
  .finished { text-align: center; padding: 2rem; }
  .online-note { color: var(--muted); font-size: 0.85rem; margin-top: 0.75rem; }
  .online-error { color: var(--red); font-size: 0.85rem; margin-top: 0.75rem; }
  .trophy { font-size: 2rem; margin-bottom: 0.5rem; }
  .winner-name { font-size: 1.5rem; font-weight: 700; color: var(--green); }
  .winner-label { color: var(--muted); margin: 0.5rem 0 1.5rem; }
  .finished-actions { display: flex; gap: 0.5rem; justify-content: center; }
  .btn-undo-win {
    display: block; margin: 1rem auto 0; background: none; border: none;
    color: var(--muted); font-size: 0.8rem; text-decoration: underline;
    cursor: pointer;
  }
  .btn-undo-win:hover { color: var(--text); }
  .elim-section-title { font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 1rem; }
  .hint { color: var(--muted); font-size: 0.75rem; text-transform: none; letter-spacing: normal; }
  .lives-row { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 1rem; }
  .lives-row .label { font-size: 0.9rem; color: var(--muted); }
  .counter { display: flex; align-items: center; gap: 0.5rem; }
  .counter-val { font-size: 1.3rem; font-weight: 700; min-width: 2rem; text-align: center; }
  .btn-counter { background: var(--bg); border: 1px solid var(--border); color: var(--text); border-radius: 6px; width: 2rem; height: 2rem; cursor: pointer; font-size: 1.1rem; display: flex; align-items: center; justify-content: center; }
  .btn-counter:hover { border-color: var(--accent); }
  .game-players { list-style: none; margin-bottom: 1rem; padding: 0; }
  .game-players li { display: flex; align-items: center; gap: 0.5rem; padding: 0.4rem 0; border-bottom: 1px solid var(--border); }
  .game-players li:last-child { border: none; }
  .player-name-text { flex: 1; font-size: 0.95rem; }
  .btn-icon { background: none; border: 1px solid var(--border); border-radius: 6px; color: var(--muted); cursor: pointer; padding: 0.2rem 0.45rem; font-size: 0.8rem; }
  .btn-icon:hover { border-color: var(--accent); color: var(--text); }
  .btn-icon.remove:hover { border-color: var(--red); color: var(--red); }
  .known-chips { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-bottom: 1rem; }
  .chip { background: var(--bg); border: 1px solid var(--border); color: var(--text); border-radius: 20px; padding: 0.3rem 0.7rem; font-family: inherit; font-size: 0.85rem; cursor: pointer; }
  .chip:hover { border-color: var(--accent); color: var(--accent); }
  .chip.in-game { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
  .add-row { display: flex; gap: 0.5rem; margin-top: 1rem; }
  .add-row input {
    flex: 1; background: var(--bg); border: 1px solid var(--border); color: var(--text);
    border-radius: 6px; padding: 0.45rem 0.75rem; font-size: 0.9rem;
  }
  .add-row input:focus { outline: none; border-color: var(--accent); }
  .btn { border: none; border-radius: 8px; padding: 0.65rem 1.5rem; font-size: 0.95rem; font-weight: 600; cursor: pointer; transition: opacity 0.15s; }
  .btn:hover { opacity: 0.85; }
  .btn:disabled { opacity: 0.4; cursor: default; }
  .btn-start { background: #166534; color: #fff; }
  .btn-add { background: var(--surface); border: 1px solid var(--border); color: var(--text); padding: 0.5rem 1rem; }
  .modal-overlay {
    position: fixed; inset: 0; z-index: 100;
    display: flex; align-items: flex-start; justify-content: center;
    overflow-y: auto; padding: 1.5rem 1rem;
  }
  .overlay-backdrop {
    position: absolute; inset: 0; z-index: 0;
    background: rgba(0,0,0,0.6); border: none; padding: 0; cursor: default;
  }
  .modal-box {
    position: relative; z-index: 1;
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 1.25rem;
    max-width: 480px; width: 100%;
  }
  .modal-actions { display: flex; gap: 0.5rem; margin-top: 1.25rem; }
</style>
