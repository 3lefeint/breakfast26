<script>
  import { confirmDialog, alertDialog } from '../../lib/confirm.js';
  import { navigate } from '../../lib/router.js';
  import { t } from '../../lib/i18n.js';
  // Ports #elimFinished + #rematchModal of the former tv.html — same default-order
  // rematch logic as Home's EliminationFinished.svelte, plus the
  // TV-only "Done" button — stops the game server-side and navigates to Home's Elimination tab.
  import { shownName, storedName } from '../../lib/util.js';
  import { api, apiJson } from '../../lib/api.js';
  import { players } from '../../lib/stores/players.js';
  import Avatar from '../../lib/components/Avatar.svelte';
  import Crown from '../../lib/components/Crown.svelte';
  import { gameState } from '../../lib/stores/gameState.js';
  import ConfettiBurst from '../../lib/components/ConfettiBurst.svelte';
  import { dartLabel } from '../../lib/killer.js';
  import DartCorrectModal from './DartCorrectModal.svelte';
  import MatchAchievements from '../../lib/components/MatchAchievements.svelte';

  let { elimination, online = null } = $props();
  let lastDarts = $derived(elimination.last_turn?.darts || []);
  // The winner first, then the others in the reverse order in which they went out.
  let rows = $derived([elimination.winner, ...[...(elimination.elimination_order || [])].reverse()].filter(Boolean)
    .map((name) => ({ name, lives: (elimination.players || []).find((p) => p.name === name)?.lives || 0 })));
  let correctingIndex = $state(null);

  let showModal = $state(false);
  let rematchPlayers = $state([]);
  let rematchNewInsertIdx = $state(0);
  let rematchLives = $state(3);
  let newPlayerName = $state('');

  function openRematchModal() {
    rematchPlayers = [...(elimination.elimination_order || []), elimination.winner].filter(Boolean);
    rematchNewInsertIdx = 0;
    rematchLives = elimination.lives_max || 3;
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
    const name = storedName(newPlayerName);
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
    if (rematchPlayers.length < 2) { alertDialog(t('Select at least 2 players.')); return; }
    await api('POST', '/api/elimination/start', { players: rematchPlayers, lives: rematchLives });
    showModal = false;
  }

  let onlineError = $state('');
  async function onlineRematch() {
    const res = await apiJson('POST', '/api/online/rematch');
    onlineError = res.error ? t(res.error) : '';
    if (!res.error) navigate('elimination');   // the lobby is on Home
  }
  async function finishDone() {
    await api('POST', '/api/elimination/stop');
    navigate('elimination');
  }
  async function undoWin() {
    // Resumes the match server-side and un-records the win from
    // stats.db — for a match-ending dart that turned out to be
    // misdetected. App.svelte switches back to the live view on its own
    // once elimination.state flips back to "playing".
    if (!await confirmDialog(t('Undo the winning turn and resume the match?'))) return;
    await api('POST', '/api/elimination/undo');
  }
</script>

<ConfettiBurst />

<div class="finished">
  <div class="heading">{t('{name} wins', { name: shownName(elimination.winner || '') })}</div>
  <ul class="results">
    {#each rows as p, i (p.name)}
      <li class:winner={p.name === elimination.winner}>
        <span class="place">{i + 1}</span>
        <span class="who">
          <span class="swatch"><Avatar name={p.name || ''} color={$gameState.player_colors?.[p.name] || null} size={100} /></span>
          <span class="name-crown">{#if p.name === elimination.winner}<Crown />{/if}{shownName(p.name)}</span>
        </span>
        <span class="lives">{p.lives > 0 ? '❤️'.repeat(p.lives) : '☠️'}</span>
      </li>
    {/each}
  </ul>
  {#if lastDarts.length && !online}
    <div class="last">
      <span class="last-label">{t('Last turn, {name}', { name: shownName(elimination.last_turn.player) })}</span>
      {#each lastDarts as d, i}
        <button type="button" class="dart-chip" onclick={() => (correctingIndex = i)}>{dartLabel(d)}</button>
      {/each}
    </div>
  {/if}
  <MatchAchievements matchId={elimination.match_id} large />
  <div class="finished-actions">
    {#if !online}
      <button class="btn btn-start" onclick={openRematchModal}>{t('↻ Rematch')}</button>
    {:else if online.host}
      <button class="btn btn-start" onclick={onlineRematch}>{t('↻ Rematch')}</button>
    {/if}
    {#if !online}<button class="btn btn-add" onclick={undoWin}>{t('↩ Undo')}</button>{/if}
    <button class="btn btn-add" onclick={finishDone}>{t('✓ Done')}</button>
  </div>
  {#if online && !online.host}<p class="online-note">{t('Only the host can start a rematch.')}</p>{/if}
  {#if onlineError}<p class="online-error">{onlineError}</p>{/if}
</div>

{#if showModal}
  <div class="modal-overlay">
    <button type="button" class="overlay-backdrop" aria-label={t('Close')} onclick={closeRematchModal}></button>
    <div class="modal-box">
      <div class="elim-section-title">{t('Rematch')}</div>

      <div class="lives-row">
        <span class="label">{t('Lives per player')}</span>
        <div class="counter">
          <button class="btn-counter" onclick={() => changeRematchLives(-1)}>−</button>
          <span class="counter-val">{rematchLives}</span>
          <button class="btn-counter" onclick={() => changeRematchLives(+1)}>+</button>
        </div>
      </div>

      <div class="elim-section-title">{t('Players')} <span class="hint">{t('(first loser starts first, winner last)')}</span></div>
      <ul class="game-players">
        {#each rematchPlayers as name, i (name + i)}
          <li>
            <span class="player-name-text">{shownName(name)}</span>
            <button class="btn-icon" onclick={() => moveRematchPlayer(i, -1)} disabled={i === 0}>↑</button>
            <button class="btn-icon" onclick={() => moveRematchPlayer(i, +1)} disabled={i === rematchPlayers.length - 1}>↓</button>
            <button class="btn-icon remove" onclick={() => removeFromRematch(i)}>×</button>
          </li>
        {/each}
      </ul>

      <div class="add-row">
        <input type="text" placeholder={t('Add new player (starts first)')} bind:value={newPlayerName}
               onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addNewRematchPlayer(); } }}>
        <button class="btn btn-add" onclick={addNewRematchPlayer}>{t('+ Add')}</button>
      </div>

      <div class="elim-section-title">{t('Known players')} <span class="hint">{t('(click to add/remove)')}</span></div>
      <div class="known-chips">
        {#each $players.known as name (name)}
          <button type="button" class="chip" class:in-game={rematchPlayers.includes(name)} onclick={() => toggleRematchPlayer(name)}>{shownName(name)}</button>
        {/each}
      </div>

      <div class="modal-actions">
        <button class="btn btn-add" onclick={closeRematchModal}>{t('Cancel')}</button>
        <button class="btn btn-start" onclick={startRematch}>{t('▶ Start rematch')}</button>
      </div>
    </div>
  </div>
{/if}

{#if correctingIndex != null}
  <DartCorrectModal dartIndex={correctingIndex} onClose={() => (correctingIndex = null)}
                    endpoint="/api/elimination/correct-last-dart" />
{/if}

<style>
  .finished { flex: 1; min-height: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 1.4rem; padding: 1.5rem 2rem; }
  .heading { font-size: clamp(2rem, 5vw, 4.2rem); font-weight: 800; color: var(--green); text-align: center; }
  .results { list-style: none; padding: 0; width: min(36rem, 90vw); max-height: 42vh; overflow-y: auto; }
  .results li {
    display: grid; grid-template-columns: 2.5rem 1fr auto; align-items: center; gap: 1rem;
    padding: 0.6rem 1.2rem; margin-top: 0.6rem; border-radius: 16px;
    background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); font-size: clamp(1.1rem, 2.2vw, 1.9rem);
  }
  .results li.winner { border-color: color-mix(in srgb, var(--green) 55%, transparent); }
  .place { color: var(--muted); font-weight: 700; }
  .who { display: flex; align-items: center; gap: 0.7em; }
  .name-crown { position: relative; display: inline-block; }
  .swatch { width: 1.5em; height: 1.5em; border-radius: 50%; flex-shrink: 0; align-self: center; overflow: visible; }
  .swatch :global(svg) { width: 100%; height: 100%; }
  .finished-actions { display: flex; gap: 1vw; justify-content: center; }
  .finished-actions .btn { border-radius: 999px; padding: 0.75rem 2rem; font-size: clamp(1rem, 1.5vw, 1.6rem); transition: border-color 0.15s, color 0.15s, background 0.15s; }
  .finished-actions .btn:hover { opacity: 1; }
  .finished-actions .btn-start:hover { background: #15803d; }
  .finished-actions .btn-add { box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2); }
  .finished-actions .btn-add:hover { border-color: var(--accent); }
  .online-note { color: var(--muted); font-size: 0.9rem; margin-top: 1rem; }
  .online-error { color: var(--red); font-size: 0.9rem; margin-top: 1rem; }
  .last { display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap; justify-content: center; }
  .last-label { color: var(--muted); font-size: clamp(0.85rem, 1.4vw, 1.3rem); }
  .dart-chip { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 10px; padding: 0.4rem 1rem; font-family: inherit; font-size: clamp(1rem, 1.8vw, 1.6rem); font-weight: 700; color: var(--text); cursor: pointer; }
  .dart-chip:hover { border-color: var(--accent); }
  .elim-section-title { font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 1rem; }
  .hint { color: var(--muted); font-size: 0.75rem; text-transform: none; letter-spacing: normal; }
  .lives-row { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 1rem; }
  .lives-row .label { font-size: 0.9rem; color: var(--muted); }
  .counter { display: flex; align-items: center; gap: 0.5rem; }
  .counter-val { font-size: 1.3rem; font-weight: 700; min-width: 2rem; text-align: center; }
  .btn-counter { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 10px; width: 2rem; height: 2rem; cursor: pointer; font-size: 1.1rem; display: flex; align-items: center; justify-content: center; }
  .btn-counter:hover { border-color: var(--accent); }
  .game-players { list-style: none; margin-bottom: 1rem; padding: 0; }
  .game-players li { display: flex; align-items: center; gap: 0.5rem; padding: 0.4rem 0; border-bottom: 1px solid var(--glass-border); }
  .game-players li:last-child { border: none; }
  .player-name-text { flex: 1; font-size: 0.95rem; }
  .btn-icon { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 6px; color: var(--muted); cursor: pointer; padding: 0.2rem 0.45rem; font-size: 0.8rem; }
  .btn-icon:hover { border-color: var(--accent); color: var(--text); }
  .btn-icon.remove:hover { border-color: var(--red); color: var(--red); }
  .known-chips { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-bottom: 1rem; }
  .chip { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 20px; padding: 0.3rem 0.7rem; font-family: inherit; font-size: 0.85rem; cursor: pointer; }
  .chip:hover { border-color: var(--accent); color: var(--accent); }
  .chip.in-game { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
  .add-row { display: flex; gap: 0.5rem; margin-top: 1rem; }
  .add-row input { flex: 1; background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); color: var(--text); border-radius: 12px; padding: 0.55rem 0.75rem; font-size: 0.95rem; }
  .add-row input:focus { outline: none; border-color: var(--accent); }
  .btn { border: none; border-radius: 8px; padding: 0.65rem 1.5rem; font-size: 0.95rem; font-weight: 600; cursor: pointer; transition: opacity 0.15s; }
  .btn:hover { opacity: 0.85; }
  .btn:disabled { opacity: 0.4; cursor: default; }
  .btn-start { background: #166534; color: #fff; }
  .btn-add { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); padding: 0.5rem 1rem; }
  .modal-overlay { position: fixed; inset: 0; z-index: 100; display: flex; align-items: flex-start; justify-content: center; overflow-y: auto; padding: 1.5rem 1rem; }
  .overlay-backdrop { position: absolute; inset: 0; z-index: 0; background: rgba(3, 8, 20, 0.55); backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px); border: none; padding: 0; cursor: default; }
  .modal-box { position: relative; z-index: 1; background: var(--surface); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); border-radius: 16px; padding: 1.25rem; max-width: 480px; width: 100%; }
  .modal-actions { display: flex; gap: 0.5rem; margin-top: 1.25rem; }
</style>
