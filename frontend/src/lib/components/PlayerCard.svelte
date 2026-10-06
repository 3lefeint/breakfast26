<script>
  import { t } from '../i18n.js';
  // One row of the list of known players: avatar, name (opens the profile), the Elimination and X01
  // win counts, whether there is a recording of the name and Hide. The columns match the header row
  // of Players.svelte (`.player-row-header`).
  import Icon from './Icon.svelte';
  import Avatar from './Avatar.svelte';

  let { name, wins = 0, x01Wins = 0, missingAudio = false, onHide = null, href = null, color = null } = $props();
</script>

<li class="player-card">
  <span class="avatar"><Avatar {name} {color} size={40} /></span>
  {#if href}
    <a class="pname" {href}>{name}</a>
  {:else}
    <span class="pname">{name}</span>
  {/if}
  <span class="stats">
    <span class="pwins">{#if wins}<Icon name="trophy" size={16} /> {wins}{/if}</span>
    <span class="pwins">{#if x01Wins}<Icon name="board" size={16} /> {x01Wins}{/if}</span>
    <span class="paudio">
      {#if missingAudio}
        <span class="no-audio-icon" title={t('No recording for this name')}><Icon name="volume-off" size={18} /></span>
      {/if}
    </span>
  </span>
  <span class="phide">
    {#if onHide}
      <button class="btn-hide" onclick={() => onHide(name)}>{t('Hide')}</button>
    {/if}
  </span>
</li>

<style>
  .player-card {
    display: grid;
    grid-template-columns: 2.6rem 1fr 6rem 6rem 3rem 4.5rem;
    align-items: center;
    gap: 0.75rem;
    padding: 0.6rem 0.75rem;
    border-radius: 12px;
    transition: background 0.15s;
  }
  .player-card:hover { background: var(--glass); }
  /* The three values share the columns of the header row. */
  .stats { display: contents; }
  .avatar { display: flex; align-items: center; justify-content: center; }
  .pname { color: var(--text); text-decoration: none; font-size: 1.05rem; text-transform: capitalize; }
  a.pname:hover { color: var(--accent); }
  .pwins { display: flex; align-items: center; gap: 0.35rem; color: color-mix(in srgb, var(--text) 75%, transparent); font-size: 0.95rem; }
  .pwins :global(svg) { color: var(--accent); }
  .paudio, .phide { display: flex; justify-content: flex-end; }
  .no-audio-icon { color: var(--red); display: flex; }
  .btn-hide {
    background: var(--glass); border: 1px solid var(--glass-border); color: var(--muted);
    font-size: 0.8rem; padding: 0.3rem 0.8rem; border-radius: 999px; cursor: pointer; font-family: inherit;
    transition: border-color 0.15s, color 0.15s;
  }
  .btn-hide:hover { border-color: var(--accent); color: var(--accent); }

  /* Narrow screens: the values go under the name. */
  @media (max-width: 640px) {
    .player-card { grid-template-columns: 2.6rem 1fr auto; row-gap: 0.1rem; }
    .stats { display: flex; align-items: center; gap: 1rem; grid-column: 2; grid-row: 2; }
    .pname { grid-column: 2; grid-row: 1; }
    .avatar { grid-row: 1 / span 2; }
    .phide { grid-column: 3; grid-row: 1 / span 2; }
    .paudio { order: -1; }
  }
</style>
