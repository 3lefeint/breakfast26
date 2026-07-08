<script>
  // Mirrors index.html's #view-players: known list (name/wins/audio-icon/
  // Hide), add-player input, and the hidden-players section with Unhide.
  import { players } from '../../lib/stores/players.js';
  import { api } from '../../lib/api.js';
  import { cap } from '../../lib/util.js';
  import PlayerCard from '../../lib/components/PlayerCard.svelte';
  import PageHeader from '../../lib/components/PageHeader.svelte';

  let newPlayerName = $state('');

  async function addPlayer() {
    const name = newPlayerName.trim();
    if (!name) return;
    await api('POST', '/api/players', { name });
    newPlayerName = '';
  }
  async function hidePlayer(name) {
    await api('PATCH', `/api/players/${encodeURIComponent(name)}/hidden`, { hidden: true });
  }
  async function unhidePlayer(name) {
    await api('PATCH', `/api/players/${encodeURIComponent(name)}/hidden`, { hidden: false });
  }
</script>

<PageHeader title="Players" />

<div class="elim-section">
  <div class="elim-section-title">Known players</div>
  <div class="player-row-header">
    <span>Name</span>
    <span>Elimination Wins</span>
    <span>X01 Wins</span>
    <span class="right">Audio</span>
    <span></span>
  </div>
  <ul class="known-list">
    {#each $players.known as name (name)}
      <PlayerCard
        {name}
        wins={$players.winsFor(name)}
        x01Wins={$players.x01WinsFor(name)}
        missingAudio={$players.missingAudio(name)}
        onHide={hidePlayer}
      />
    {/each}
  </ul>
  <div class="add-row">
    <input type="text" placeholder="Name" bind:value={newPlayerName}
           onkeydown={(e) => e.key === 'Enter' && addPlayer()}>
    <button class="btn btn-add" onclick={addPlayer}>+ Add</button>
  </div>
</div>

{#if $players.hidden.length}
  <div class="elim-section hidden-section">
    <div class="elim-section-title muted">Hidden players</div>
    <ul class="hidden-players-list">
      {#each $players.hidden as name (name)}
        <li>
          <span class="pname">{cap(name)}</span>
          <button class="btn-hide" onclick={() => unhidePlayer(name)}>Unhide</button>
        </li>
      {/each}
    </ul>
  </div>
{/if}

<style>
  .elim-section {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 1.25rem; margin-bottom: 1rem;
  }
  .hidden-section { margin-top: 1rem; }
  .elim-section-title { font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 1rem; }
  .elim-section-title.muted { font-size: 0.85rem; }
  .player-row-header {
    display: grid; grid-template-columns: 1fr 8rem 6rem 3rem 4rem; gap: 0.5rem;
    font-size: 0.7rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em;
    padding: 0 0 0.4rem; border-bottom: 1px solid var(--border);
  }
  .player-row-header .right { text-align: right; }
  .known-list, .hidden-players-list { list-style: none; padding: 0; }
  .hidden-players-list li {
    display: flex; align-items: center;
    padding: 0.5rem; border-bottom: 1px solid var(--border);
  }
  .hidden-players-list li:last-child { border: none; }
  .pname { flex: 1; font-size: 0.85rem; }
  .btn-hide {
    background: transparent; border: 1px solid var(--border); color: var(--muted);
    font-size: 0.7rem; padding: 0.15rem 0.4rem; border-radius: 4px; cursor: pointer;
  }
  .btn-hide:hover { border-color: var(--accent); color: var(--accent); }
  .add-row { display: flex; gap: 0.5rem; margin-top: 1rem; }
  .add-row input {
    flex: 1; background: var(--bg); border: 1px solid var(--border); color: var(--text);
    border-radius: 6px; padding: 0.45rem 0.75rem; font-size: 0.9rem;
  }
  .add-row input:focus { outline: none; border-color: var(--accent); }
  .btn { border: none; border-radius: 8px; padding: 0.65rem 1.5rem; font-size: 0.95rem; font-weight: 600; cursor: pointer; transition: opacity 0.15s; }
  .btn:hover { opacity: 0.85; }
  .btn-add { background: var(--surface); border: 1px solid var(--border); color: var(--text); padding: 0.5rem 1rem; }
</style>
