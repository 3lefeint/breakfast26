<script>
  import { t } from '../../lib/i18n.js';
  // Killer setup: players (order = play order, or random) and the two options. Every player gets a
  // random number when the game starts. Local state until Start is pressed.
  import { players } from '../../lib/stores/players.js';
  import { apiJson } from '../../lib/api.js';
  import Toggle from '../../lib/components/Toggle.svelte';
  import NewPlayer from '../../lib/components/NewPlayer.svelte';
  import { cap } from '../../lib/util.js';
  import BotAdder from '../../lib/components/BotAdder.svelte';

  const MAX_PLAYERS = 20;

  let gamePlayers = $state([]);
  let bots = $state({});
  let ownGoal = $state(false);
  let singles = $state(false);
  let bullOff = $state(true);
  let throwNumbers = $state(true);
  let randomOrder = $state(false);

  function toggle(name) {
    const idx = gamePlayers.indexOf(name);
    if (idx >= 0) gamePlayers.splice(idx, 1);
    else if (gamePlayers.length < MAX_PLAYERS) gamePlayers.push(name);
  }
  function added(name) { if (!gamePlayers.includes(name)) gamePlayers.push(name); }
  function removeFromGame(i) { delete bots[gamePlayers[i]]; gamePlayers.splice(i, 1); }
  function movePlayer(i, dir) {
    const j = i + dir;
    if (j < 0 || j >= gamePlayers.length) return;
    [gamePlayers[i], gamePlayers[j]] = [gamePlayers[j], gamePlayers[i]];
  }

  function shuffled(arr) {
    const result = arr.slice();
    for (let i = result.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [result[i], result[j]] = [result[j], result[i]];
    }
    return result;
  }

  async function start() {
    if (gamePlayers.length < 2) { alert(t('Select at least 2 players.')); return; }
    const order = randomOrder ? shuffled(gamePlayers) : gamePlayers;
    const res = await apiJson('POST', '/api/killer/start', {
      players: order, own_goal: ownGoal, singles, bull_off: bullOff, throw_numbers: throwNumbers, bots,
    });
    if (res.error) { alert(t(res.error)); return; }
    window.location.href = '/tv';
  }
</script>

<div class="section">
  <div class="top">
    <div class="left">
      <Toggle wide bind:checked={bullOff} label={t('Bull-off: everybody throws one dart at the bull, the closest one starts')} />
      <Toggle wide bind:checked={throwNumbers} label={t('Throw for the numbers: everybody throws one dart with the other hand and gets the number it hits (a double makes a killer at once). Off: the numbers are drawn at random')} />

      <Toggle wide bind:checked={singles} label={t('Singles take lives too, not only doubles (triples never do)')} />
      <Toggle wide bind:checked={ownGoal} label={t('Own goal: a killer who hits their own number loses a life')} />

      <Toggle bind:checked={randomOrder} label={t('Random order')} />

      <div class="section-title">{t('Choose Players')}</div>
      <div class="known-chips">
        {#each $players.known as name (name)}
          <button type="button" class="chip" class:in-game={gamePlayers.includes(name)} onclick={() => toggle(name)}>{cap(name)}</button>
        {/each}
      </div>
      <NewPlayer onadded={added} />
      <BotAdder bind:gamePlayers bind:bots max={MAX_PLAYERS} />
    </div>

    <!-- The same word in both languages; t('Players') is taken by the navigation. -->
    <div class="right">
      <div class="section-title">Players</div>
      <ul class="game-players">
        {#each gamePlayers as name, i (name)}
          <li>
            <span class="player-name-text">{cap(name)}{#if bots[name]} <span class="bot-tag">{t('Computer')} {bots[name]}+</span>{/if}</span>
            <button class="btn-icon" onclick={() => movePlayer(i, -1)} disabled={i === 0}>↑</button>
            <button class="btn-icon" onclick={() => movePlayer(i, +1)} disabled={i === gamePlayers.length - 1}>↓</button>
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
  .hint { color: var(--muted); font-size: 0.75rem; text-transform: none; letter-spacing: normal; }
  .option-row { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 1rem; flex-wrap: wrap; }
  .option-row .label { font-size: 0.9rem; color: var(--muted); min-width: 8rem; }
  .counter { display: flex; align-items: center; gap: 0.5rem; }
  .counter-val { font-size: 1.15rem; font-weight: 700; min-width: 1.4rem; text-align: center; }
  .btn-counter { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 8px; min-width: 1.5rem; height: 1.5rem; padding: 0 0.3rem; cursor: pointer; font-size: 0.95rem; line-height: 1; display: flex; align-items: center; justify-content: center; }
  .btn-counter:hover { border-color: var(--accent); }
  .seg { display: flex; gap: 0.4rem; }
  .seg-btn { background: var(--glass); border: 1px solid var(--glass-border); color: var(--muted); border-radius: 20px; padding: 0.3rem 0.9rem; font-family: inherit; font-size: 0.85rem; cursor: pointer; }
  .seg-btn:hover { border-color: var(--accent); color: var(--text); }
  .seg-btn.active { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); font-weight: 700; }
  .targets { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; margin: -0.25rem 0 1rem 5.75rem; }
  .target-cell { display: flex; flex-direction: column; align-items: center; gap: 0.15rem; font-size: 0.7rem; color: var(--muted); }
  .target-cell input { width: 3.2rem; background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 12px; color: var(--text); padding: 0.25rem; text-align: center; font-family: inherit; }
  select { background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 12px; color: var(--text); padding: 0.35rem 0.5rem; font-family: inherit; }
  /* The left column has a fixed height, the list of players on the right fills it and scrolls: nothing moves
     when players are added. */
  .top { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 1.5rem; align-items: stretch; margin-bottom: 1.2rem; }
  .right { display: flex; flex-direction: column; min-height: 0; }
  .right .section-title { margin-bottom: 0.5rem; }
  @media (max-width: 900px) { .top { grid-template-columns: 1fr; } .game-players { max-height: 14rem; flex: none; } }
  .known-chips { display: flex; flex-wrap: wrap; gap: 0.4rem; align-content: flex-start; height: 8.5rem; overflow-y: auto; }
  .chip { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 20px; padding: 0.3rem 0.7rem; font-family: inherit; font-size: 0.85rem; cursor: pointer; transition: border-color 0.15s, color 0.15s; }
  .chip:hover { border-color: var(--accent); color: var(--accent); }
  .chip.in-game { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
  .game-players { list-style: none; margin: 0; padding: 0; flex: 1 1 0; min-height: 0; overflow-y: auto; }
  .game-players li { display: flex; align-items: center; gap: 0.5rem; padding: 0.4rem 0; border-bottom: 1px solid var(--glass-border); }
  .game-players li:last-child { border: none; }
  .player-name-text { flex: 1; font-size: 0.95rem; }
  .bot-tag { color: var(--muted); font-size: 0.75rem; margin-left: 0.4rem; }
  .btn-icon { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 6px; color: var(--muted); cursor: pointer; padding: 0.2rem 0.45rem; font-size: 0.8rem; }
  .btn-icon:hover { border-color: var(--accent); color: var(--text); }
  .btn-icon.remove:hover { border-color: var(--red); color: var(--red); }
  .btn { border: none; border-radius: 8px; padding: 0.65rem 1.5rem; font-size: 0.95rem; font-weight: 600; cursor: pointer; transition: opacity 0.15s; }
  .btn:hover { opacity: 0.85; }
  .btn-start { background: #166534; color: #fff; }
</style>
