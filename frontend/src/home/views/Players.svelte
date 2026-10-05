<script>
  // The known players (name, wins, audio, Hide), the form that adds one, and the hidden players with
  // Unhide.
  import { players } from '../../lib/stores/players.js';
  import { gameState } from '../../lib/stores/gameState.js';
  import { api } from '../../lib/api.js';
  import { cap } from '../../lib/util.js';
  import PlayerCard from '../../lib/components/PlayerCard.svelte';
  import PageHeader from '../../lib/components/PageHeader.svelte';
  import Panel from '../../lib/components/Panel.svelte';
  import Icon from '../../lib/components/Icon.svelte';

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

<PageHeader title="Players" back="#home" />

<Panel>
  <div class="player-row-header">
    <span></span>
    <span>Name</span>
    <span>Elimination</span>
    <span>X01</span>
    <span class="right">Audio</span>
    <span></span>
  </div>
  <ul class="known-list">
    {#each $players.known as name (name)}
      <PlayerCard
        {name}
        href={`#profile/${encodeURIComponent(name)}`}
        wins={$players.winsFor(name)}
        x01Wins={$players.x01WinsFor(name)}
        missingAudio={$players.missingAudio(name)}
        color={$gameState.player_colors?.[name] || null}
        onHide={hidePlayer}
      />
    {/each}
  </ul>
  <div class="add-row">
    <input type="text" placeholder="Name" bind:value={newPlayerName}
           onkeydown={(e) => e.key === 'Enter' && addPlayer()}>
    <button class="btn-add" onclick={addPlayer}><Icon name="plus" size={18} stroke={2.2} /> Add</button>
  </div>
</Panel>

{#if $players.hidden.length}
  <Panel title="Hidden players">
    <ul class="hidden-players-list">
      {#each $players.hidden as name (name)}
        <li>
          <span class="pname">{cap(name)}</span>
          <button class="btn-hide" onclick={() => unhidePlayer(name)}>Unhide</button>
        </li>
      {/each}
    </ul>
  </Panel>
{/if}

<style>
  .player-row-header {
    display: grid; grid-template-columns: 2.6rem 1fr 6rem 6rem 3rem 4.5rem; gap: 0.75rem;
    padding: 0 0.75rem 0.6rem; margin-bottom: 0.4rem;
    font-size: 0.72rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em;
    border-bottom: 1px solid var(--glass-border);
  }
  .player-row-header .right { text-align: right; }
  .known-list, .hidden-players-list { list-style: none; padding: 0; }
  .hidden-players-list li { display: flex; align-items: center; padding: 0.6rem 0.75rem; border-radius: 12px; }
  .hidden-players-list li:hover { background: var(--glass); }
  .pname { flex: 1; font-size: 1rem; color: color-mix(in srgb, var(--text) 80%, transparent); }
  .btn-hide {
    background: var(--glass); border: 1px solid var(--glass-border); color: var(--muted);
    font-size: 0.8rem; padding: 0.3rem 0.8rem; border-radius: 999px; cursor: pointer; font-family: inherit;
    transition: border-color 0.15s, color 0.15s;
  }
  .btn-hide:hover { border-color: var(--accent); color: var(--accent); }
  .add-row { display: flex; gap: 0.75rem; margin-top: 1.25rem; padding-top: 1.25rem; border-top: 1px solid var(--glass-border); }
  .add-row input {
    flex: 1; background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); color: var(--text);
    border-radius: 12px; padding: 0.65rem 1rem; font-size: 1rem; font-family: inherit;
  }
  .add-row input::placeholder { color: var(--muted); }
  .add-row input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 25%, transparent); }
  .btn-add {
    display: inline-flex; align-items: center; gap: 0.4rem; padding: 0.65rem 1.3rem; border-radius: 12px; cursor: pointer;
    font-size: 1rem; font-weight: 600; font-family: inherit; color: #0c0c0f;
    background: var(--accent); border: 1px solid var(--accent); transition: opacity 0.15s;
  }
  .btn-add:hover { opacity: 0.85; }

  @media (max-width: 640px) {
    .player-row-header { display: none; }
  }
</style>
