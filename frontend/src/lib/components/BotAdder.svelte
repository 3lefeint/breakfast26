<script>
  import { t } from '../i18n.js';
  // Adds a computer opponent to the game players of a setup page: a level (its 3-dart average) and a
  // name. `bots` maps the name of every computer player in `gamePlayers` to its level.
  import { players } from '../stores/players.js';

  // `stageName`: a game's own scale of stages 1 to `stageCount` (weakest first) with their names; without it the
  // levels are the 3-dart averages 10 to 110.
  let { gamePlayers = $bindable(), bots = $bindable(), max = 20, onadded = null, stageName = null, stageCount = 5 } = $props();

  const LEVELS = $derived(stageName ? Array.from({ length: stageCount }, (_, i) => i + 1) : Array.from({ length: 11 }, (_, i) => 10 + i * 10));
  const label = (l) => (stageName ? stageName(l) : `${l}+`);
  let level = $state(stageName ? 2 : 60);
  let name = $state('');

  function uniqueName() {
    const base = name.trim() || `${t('Bot')} ${stageName ? label(level) : level}`;
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
    onadded?.();
  }

  const clash = $derived($players.known.some((p) => p.toLowerCase() === name.trim().toLowerCase()) && name.trim() !== '');
</script>

<div class="bot-adder">
  <div class="title">{t('Computer opponent')}</div>
  <div class="row">
    <label>
      <span>{stageName ? t('Skill') : t('Level (3-dart average)')}</span>
      <select bind:value={level}>
        {#each LEVELS as l (l)}<option value={l}>{label(l)}</option>{/each}
      </select>
    </label>
    <label>
      <span>{t('Name')}</span>
      <input type="text" bind:value={name} placeholder={`${t('Bot')} ${stageName ? label(level) : level}`} maxlength="24">
    </label>
    <button type="button" class="add" onclick={add} disabled={clash || gamePlayers.length >= max}>{t('+ Add')}</button>
  </div>
  {#if clash}<div class="warn">{t('a bot cannot have the name of a player')}</div>{/if}
</div>

<style>
  .bot-adder { margin: 1.4rem 0 1rem; }
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
