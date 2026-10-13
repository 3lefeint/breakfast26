<script>
  import { t } from '../i18n.js';
  // Adds a computer opponent to the game players of a setup page: a level (its 3-dart average) and a
  // name. `bots` maps the name of every computer player in `gamePlayers` to its level.
  import { players } from '../stores/players.js';

  let { gamePlayers = $bindable(), bots = $bindable(), max = 20 } = $props();

  const LEVELS = Array.from({ length: 11 }, (_, i) => 10 + i * 10);
  let level = $state(60);
  let name = $state('');

  function uniqueName() {
    const base = name.trim() || `${t('Bot')} ${level}`;
    const taken = (n) => gamePlayers.some((p) => p.toLowerCase() === n.toLowerCase());
    let candidate = base;
    for (let i = 2; taken(candidate); i++) candidate = `${base} ${i}`;
    return candidate;
  }

  function add() {
    if (gamePlayers.length >= max) return;
    const botName = uniqueName();
    gamePlayers.push(botName);
    bots[botName] = level;
    name = '';
  }

  const clash = $derived($players.known.some((p) => p.toLowerCase() === name.trim().toLowerCase()) && name.trim() !== '');
</script>

<div class="bot-adder">
  <div class="title">{t('Computer opponent')}</div>
  <div class="row">
    <label>
      <span>{t('Level (3-dart average)')}</span>
      <select bind:value={level}>
        {#each LEVELS as l (l)}<option value={l}>{l}+</option>{/each}
      </select>
    </label>
    <label>
      <span>{t('Name')}</span>
      <input type="text" bind:value={name} placeholder={`${t('Bot')} ${level}`} maxlength="24">
    </label>
    <button type="button" class="add" onclick={add} disabled={clash || gamePlayers.length >= max}>{t('+ Add')}</button>
  </div>
  {#if clash}<div class="warn">{t('a bot cannot have the name of a player')}</div>{/if}
</div>

<style>
  .bot-adder { margin-bottom: 1rem; }
  .title { font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 0.5rem; }
  .row { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: flex-end; }
  label { display: flex; flex-direction: column; gap: 0.15rem; font-size: 0.7rem; color: var(--muted); }
  select, input { background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 12px; color: var(--text); padding: 0.35rem 0.5rem; font-family: inherit; font-size: 0.85rem; }
  input { width: 8rem; }
  .add { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 20px; padding: 0.35rem 0.9rem; font-family: inherit; font-size: 0.85rem; cursor: pointer; }
  .add:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
  .add:disabled { opacity: 0.4; cursor: default; }
  .warn { color: var(--red); font-size: 0.75rem; margin-top: 0.4rem; }
</style>
