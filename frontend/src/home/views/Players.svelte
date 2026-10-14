<script>
  import { t } from '../../lib/i18n.js';
  // The known players (name, wins, audio, Hide), the form that adds one, the hidden players with
  // Unhide, and the form that merges one player into another.
  import { players } from '../../lib/stores/players.js';
  import { gameState } from '../../lib/stores/gameState.js';
  import { api, apiJson } from '../../lib/api.js';
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

  // Merge: the player that is removed (source) and the one that keeps the data (target).
  let mergeSource = $state('');
  let mergeTarget = $state('');
  let mergeMessage = $state('');
  let allPlayers = $derived([...$players.known, ...$players.hidden].sort((a, b) => a.localeCompare(b)));

  // The merge asks for a typed word first: `confirming` holds what the dialog shows.
  const CONFIRM_WORD = 'merge';
  let confirming = $state(null);
  let typed = $state('');

  async function mergePlayers() {
    mergeMessage = '';
    const query = `source=${encodeURIComponent(mergeSource)}&target=${encodeURIComponent(mergeTarget)}`;
    const preview = await apiJson('GET', `/api/players/merge-preview?${query}`);
    if (preview.error) { mergeMessage = preview.error; return; }
    typed = '';
    confirming = { source: mergeSource, target: mergeTarget, matches: preview.matches, achievements: preview.achievements };
  }

  async function confirmMerge() {
    if (typed.trim().toLowerCase() !== CONFIRM_WORD) return;
    const { source, target } = confirming;
    confirming = null;
    const res = await apiJson('POST', '/api/players/merge', { source, target });
    if (res.error) { mergeMessage = res.error; return; }
    mergeMessage = t('{source} was merged into {target}.', { source: cap(source), target: cap(target) });
    mergeSource = '';
    mergeTarget = '';
  }
</script>

<PageHeader title={t('Players')} back="#home" />

<Panel>
  <div class="player-row-header">
    <span></span>
    <span>{t('Name')}</span>
    <span>{t('Elimination')}</span>
    <span>X01</span>
    <span class="right">{t('Audio')}</span>
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
    <input type="text" placeholder={t('Name')} bind:value={newPlayerName}
           onkeydown={(e) => e.key === 'Enter' && addPlayer()}>
    <button class="btn-add" onclick={addPlayer}><Icon name="plus" size={18} stroke={2.2} /> {t('Add')}</button>
  </div>
</Panel>

{#if allPlayers.length > 1}
  <Panel title={t('Merge players')}>
    <div class="merge-row">
      <select bind:value={mergeSource} aria-label={t('From player')}>
        <option value="">{t('From player')}</option>
        {#each allPlayers.filter((n) => n !== mergeTarget) as name (name)}<option value={name}>{cap(name)}</option>{/each}
      </select>
      <Icon name="arrow" size={18} />
      <select bind:value={mergeTarget} aria-label={t('To player')}>
        <option value="">{t('To player')}</option>
        {#each allPlayers.filter((n) => n !== mergeSource) as name (name)}<option value={name}>{cap(name)}</option>{/each}
      </select>
      <button class="btn-add" disabled={!mergeSource || !mergeTarget} onclick={mergePlayers}>{t('Merge')}</button>
    </div>
    {#if mergeMessage}<p class="merge-message">{mergeMessage}</p>{/if}
  </Panel>
{/if}

{#if $players.hidden.length}
  <Panel title={t('Hidden players')}>
    <ul class="hidden-players-list">
      {#each $players.hidden as name (name)}
        <li>
          <span class="pname">{cap(name)}</span>
          <button class="btn-hide" onclick={() => unhidePlayer(name)}>{t('Unhide')}</button>
        </li>
      {/each}
    </ul>
  </Panel>
{/if}

{#if confirming}
  <div class="modal-overlay">
    <button type="button" class="overlay-backdrop" aria-label={t('Close')} onclick={() => (confirming = null)}></button>
    <div class="modal-box" role="dialog" aria-modal="true">
      <div class="modal-title">{t('Merge players')}</div>
      <p class="confirm-text">
        <span>{t('Do you want to merge {source} into {target}?', { source: cap(confirming.source), target: cap(confirming.target) })}</span>
        <span>{t('{matches} matches, {achievements} achievements', { matches: confirming.matches, achievements: confirming.achievements })}</span>
        <span>{t('{source} will be removed', { source: cap(confirming.source) })}</span>
      </p>
      <label class="confirm-label" for="mergeConfirm">{t('Type "merge" to confirm')}</label>
      <!-- svelte-ignore a11y_autofocus -->
      <input id="mergeConfirm" type="text" autocomplete="off" autofocus bind:value={typed}
             onkeydown={(e) => e.key === 'Enter' && confirmMerge()}>
      <div class="modal-buttons">
        <button type="button" class="btn-cancel" onclick={() => (confirming = null)}>{t('Cancel')}</button>
        <button type="button" class="btn-add" disabled={typed.trim().toLowerCase() !== CONFIRM_WORD} onclick={confirmMerge}>{t('Merge')}</button>
      </div>
    </div>
  </div>
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
  .merge-row { display: flex; align-items: center; gap: 0.75rem; }
  .merge-row select {
    flex: 1; min-width: 0; background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); color: var(--text);
    border-radius: 12px; padding: 0.65rem 1rem; font-size: 1rem; font-family: inherit;
  }
  .merge-row select:focus { outline: none; border-color: var(--accent); }
  .merge-row :global(svg) { color: var(--muted); flex-shrink: 0; }
  .merge-row .btn-add:disabled { opacity: 0.4; cursor: default; }
  .modal-overlay { position: fixed; inset: 0; z-index: 100; display: flex; align-items: center; justify-content: center; padding: 1.5rem 1rem; }
  .overlay-backdrop { position: absolute; inset: 0; background: rgba(3, 8, 20, 0.55); backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px); border: none; padding: 0; cursor: default; }
  .modal-box { position: relative; background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); border-radius: 16px; padding: 1.25rem; max-width: 460px; width: 100%; }
  .modal-title { font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 0.8rem; }
  .modal-box p { margin-bottom: 1rem; }
  .confirm-text span { display: block; }
  .confirm-label { display: block; font-size: 0.85rem; color: var(--muted); margin-bottom: 0.4rem; }
  .modal-box input {
    width: 100%; box-sizing: border-box; background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); color: var(--text);
    border-radius: 12px; padding: 0.65rem 1rem; font-size: 1rem; font-family: inherit;
  }
  .modal-box input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 25%, transparent); }
  .modal-buttons { display: flex; justify-content: flex-end; gap: 0.75rem; margin-top: 1.1rem; }
  .modal-buttons .btn-add:disabled { opacity: 0.4; cursor: default; }
  .btn-cancel {
    background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 12px; padding: 0.65rem 1.3rem;
    font-size: 1rem; font-family: inherit; cursor: pointer;
  }
  .btn-cancel:hover { border-color: var(--accent); }
  .merge-message { margin-top: 0.8rem; font-size: 0.9rem; }
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
    .merge-row { flex-wrap: wrap; }
    .merge-row select { flex: 1 1 100%; }
    .player-row-header { display: none; }
  }
</style>
