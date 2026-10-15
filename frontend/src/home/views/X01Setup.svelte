<script>
  import { openTv } from '../../lib/router.js';
  import { t } from '../../lib/i18n.js';
  // X01 setup: the rules (base score, in and out mode, max rounds, legs to win, bull-off) and the players. The
  // order of the players means nothing: the bull-off or the draw decides who throws first. The left column has a
  // fixed height and the list of players on the right fills it and scrolls, so nothing moves when players are added.
  // Local state until Start is pressed.
  import { players } from '../../lib/stores/players.js';
  import { apiJson } from '../../lib/api.js';
  import Toggle from '../../lib/components/Toggle.svelte';
  import NewPlayer from '../../lib/components/NewPlayer.svelte';
  import { cap } from '../../lib/util.js';
  import { START_SCORES, MODES, MAX_LEGS, MAX_ROUNDS_CHOICES } from '../../lib/x01.js';

  let gamePlayers = $state([]);
  let startScore = $state(501);
  let inMode = $state('straight');
  let outMode = $state('double');
  let legs = $state(1);
  let bullOff = $state(true);
  let maxRounds = $state(null);

  const MODE_LABEL = { straight: () => t('Straight'), double: () => t('Double'), master: () => t('Master') };

  function toggle(name) {
    const idx = gamePlayers.indexOf(name);
    if (idx >= 0) gamePlayers.splice(idx, 1);
    else gamePlayers.push(name);
  }
  function removeFromGame(i) { gamePlayers.splice(i, 1); }
  function added(name) { if (!gamePlayers.includes(name)) gamePlayers.push(name); }
  function setScore(e) {
    const n = parseInt(e.target.value, 10);
    if (Number.isFinite(n)) startScore = Math.max(2, Math.min(1501, n));
  }

  async function start() {
    if (gamePlayers.length < 1) { alert(t('Select at least 1 player.')); return; }
    const res = await apiJson('POST', '/api/x01/start', {
      players: gamePlayers, start: startScore, in_mode: inMode, out_mode: outMode, legs, bull_off: bullOff && gamePlayers.length > 1, max_rounds: maxRounds,
    });
    if (res.error) { alert(t(res.error)); return; }
    openTv();
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
        <span class="label">{t('Max Rounds')}</span>
        <div class="seg">
          {#each MAX_ROUNDS_CHOICES as n (n)}
            <button type="button" class="seg-btn" class:active={maxRounds === n} onclick={() => (maxRounds = n)}>{n ?? t('No limit')}</button>
          {/each}
        </div>
      </div>

      <div class="option-row">
        <span class="label">{t('Legs to win')}</span>
        <div class="counter">
          <button class="btn-counter" onclick={() => (legs = Math.max(1, legs - 1))}>−</button>
          <span class="counter-val">{legs}</span>
          <button class="btn-counter" onclick={() => (legs = Math.min(MAX_LEGS, legs + 1))}>+</button>
        </div>
      </div>

      <Toggle bind:checked={bullOff} label={t('Bull-Off')} />

      <div class="section-title">{t('Choose Players')}</div>
      <div class="known-chips">
        {#each $players.known as name (name)}
          <button type="button" class="chip" class:in-game={gamePlayers.includes(name)} onclick={() => toggle(name)}>{cap(name)}</button>
        {/each}
      </div>
      <NewPlayer onadded={added} />
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

  <button class="btn btn-start" onclick={start}>{t('▶ Start')}</button>
</div>

<style>
  .section { background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); border-radius: 16px; padding: 1.25rem; margin-bottom: 1rem; }
  .section-title { font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 1rem; }
  /* The left column has a fixed height, the list of players on the right fills it and scrolls: nothing moves
     when players are added. */
  .top { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 1.5rem; align-items: stretch; margin-bottom: 1.2rem; }
  .right { display: flex; flex-direction: column; min-height: 0; }
  .right .section-title { margin-bottom: 0.5rem; }
  @media (max-width: 900px) { .top { grid-template-columns: 1fr; } .game-players { max-height: 14rem; flex: none; } }
  .option-row { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.8rem; flex-wrap: wrap; }
  .option-row .label { font-size: 0.9rem; color: var(--muted); min-width: 8rem; }
  .counter { display: flex; align-items: center; gap: 0.5rem; }
  .counter-val { font-size: 1.15rem; font-weight: 700; min-width: 1.4rem; text-align: center; }
  .btn-counter { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 8px; width: 1.5rem; height: 1.5rem; cursor: pointer; font-size: 0.95rem; line-height: 1; display: flex; align-items: center; justify-content: center; }
  .btn-counter:hover { border-color: var(--accent); }
  .seg { display: flex; gap: 0.4rem; flex-wrap: wrap; align-items: center; }
  .seg-btn { background: var(--glass); border: 1px solid var(--glass-border); color: var(--muted); border-radius: 20px; padding: 0.3rem 0.9rem; font-family: inherit; font-size: 0.85rem; cursor: pointer; }
  .seg-btn:hover { border-color: var(--accent); color: var(--text); }
  .seg-btn.active { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); font-weight: 700; }
  .score-input { width: 5rem; background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 12px; color: var(--text); padding: 0.3rem 0.6rem; text-align: center; font-family: inherit; }
  @media (max-width: 640px) { .option-row .label { min-width: 0; width: 100%; } }
  .known-chips { display: flex; flex-wrap: wrap; gap: 0.4rem; align-content: flex-start; height: 8.5rem; overflow-y: auto; }
  .chip { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 20px; padding: 0.3rem 0.7rem; font-family: inherit; font-size: 0.85rem; cursor: pointer; transition: border-color 0.15s, color 0.15s; }
  .chip:hover { border-color: var(--accent); color: var(--accent); }
  .chip.in-game { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
  .game-players { list-style: none; margin: 0; padding: 0; flex: 1 1 0; min-height: 0; overflow-y: auto; }
  .game-players li { display: flex; align-items: center; gap: 0.5rem; padding: 0.4rem 0; border-bottom: 1px solid var(--glass-border); }
  .game-players li:last-child { border: none; }
  .player-name-text { flex: 1; font-size: 0.95rem; }
  .btn-icon { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 6px; color: var(--muted); cursor: pointer; padding: 0.2rem 0.45rem; font-size: 0.8rem; }
  .btn-icon.remove:hover { border-color: var(--red); color: var(--red); }
  .btn { border: none; border-radius: 8px; padding: 0.65rem 1.5rem; font-size: 0.95rem; font-weight: 600; cursor: pointer; transition: opacity 0.15s; }
  .btn:hover { opacity: 0.85; }
  .btn-start { background: #166534; color: #fff; }
</style>
