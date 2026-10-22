<script>
  import { confirmDialog } from '../../lib/confirm.js';
  import { navigate } from '../../lib/router.js';
  import { t } from '../../lib/i18n.js';
  import Avatar from '../../lib/components/Avatar.svelte';
  // Live Killer. The board is the stage: the field of every player's number is colored in the player's
  // color for the whole game, and the board shows what is open for whoever is up: the double of the
  // own number while they are no killer yet, then the fields that take a life from each opponent,
  // in the color of its owner. Beside it: the players with number, lives and status, the darts of the
  // turn (tap one to correct it) and what they did.
  import { flip } from 'svelte/animate';
  import { shownName, isBoardStopped } from '../../lib/util.js';
  import { api } from '../../lib/api.js';
  import { dartLabel, eventText, boardZones, phaseLabel } from '../../lib/killer.js';
  import LivesDisplay from '../../lib/components/LivesDisplay.svelte';
  import Icon from '../../lib/components/Icon.svelte';
  import { gameState } from '../../lib/stores/gameState.js';
  import DartBoard from '../../lib/components/DartBoard.svelte';
  import DartCorrectModal from './DartCorrectModal.svelte';

  let { killer } = $props();

  let me = $derived((killer.players || []).find((p) => p.current) || null);
  let darts = $derived(killer.darts || []);
  // Before the game one dart counts as it lands, so what is shown is the last throw, not the turn in progress.
  let preGame = $derived(killer.phase !== 'playing');
  let lastThrow = $derived(killer.last_turn?.darts?.[0] || null);
  let thrower = $derived((killer.players || []).find((p) => p.name === killer.last_turn?.player) || null);
  let markers = $derived(preGame
    ? (lastThrow ? [{ n: 1, x: lastThrow.x, y: lastThrow.y, color: thrower?.color, ring: thrower?.ring, avatar: thrower ? { name: thrower.name, color: thrower.color } : null }] : [])
    : darts.map((d, i) => ({ n: i + 1, x: d.x, y: d.y, color: me?.color, ring: me?.ring, avatar: me ? { name: me.name, color: me.color } : null })));
  let events = $derived(killer.turn_events || []);
  let livesMax = $derived(killer.lives_max || 3);
  let correctingIndex = $state(null);
  let correctingLast = $state(false);

  function ringStyle(p) {
    return p.ring ? `outline: 3px ${p.ring.dash ? 'dashed' : 'solid'} ${p.ring.color}; outline-offset: 1px;` : '';
  }

  function openCorrect(index) {
    if (killer.state !== 'playing') return;
    correctingIndex = index;
  }

  async function stop() {
    if (!await confirmDialog(t('Cancel the current game?'))) return;
    await api('POST', '/api/killer/stop');
    navigate('home');
  }

  async function resetBoard() {
    await api('POST', '/api/control/reset-board');
  }

  // The board stopped (camera standby): Start brings it back, until then there is nothing to reset.
  let boardStopped = $derived(isBoardStopped($gameState.game?.board_status));

  async function startBoard() {
    await api('POST', '/api/control/start-board');
  }

  // Ends the turn by hand, like pulling the darts.
  async function nextTurn() {
    await api('POST', '/api/killer/next');
  }

  async function undo() {
    if (!await confirmDialog(t('Undo the last completed turn?'))) return;
    await api('POST', '/api/killer/undo');
  }
</script>

<div class="k-main">
  <div class="player-card">
    <div class="name-row">
      <div class="turn">
        <span class="swatch" style="{me ? ringStyle(me) : ''}"><Avatar name={me?.name || ''} color={me?.color} size={100} /></span>
        <span class="turn-name">{shownName(killer.current_player || '—')}</span>
      </div>
      {#if phaseLabel(killer)}<span class="turn-hint">{phaseLabel(killer)}</span>{/if}
    </div>

    {#if preGame}
      <div class="darts-row single">
        <button type="button" class="dart-box" disabled={lastThrow == null} onclick={() => (correctingLast = true)}>
          <span class="dlabel">{t('Last throw')}{thrower ? ` · ${shownName(thrower.name)}` : ''}</span>
          <span class="dval">{lastThrow ? dartLabel(lastThrow) : '—'}</span>
          <span class="dsub"></span>
        </button>
      </div>
    {:else}
      <div class="darts-row">
        {#each [0, 1, 2] as i}
          <button type="button" class="dart-box" class:miss={darts[i] && dartLabel(darts[i]) === 'Miss'}
                  disabled={killer.state !== 'playing'} onclick={() => openCorrect(i)}>
            <span class="dlabel">D{i + 1}</span>
            <span class="dval">{darts[i] ? dartLabel(darts[i]) : '—'}</span>
            <span class="dsub"></span>
          </button>
        {/each}
      </div>
    {/if}

    <div class="endgame-row">
      <button class="btn-end-game" onclick={undo}>{t('↩ Undo')}</button>
      {#if killer.phase === 'playing'}<button class="btn-end-game" onclick={nextTurn}>{t('⏭ Next')}</button>{/if}
      {#if boardStopped}
        <button class="btn-end-game start" disabled={!$gameState.has_cloud_control} onclick={startBoard}><Icon name="board" size={20} />{t('Start')}</button>
      {:else}
        <button class="btn-end-game danger" disabled={!$gameState.has_cloud_control} onclick={resetBoard}><Icon name="board" size={20} />{t('Reset')}</button>
      {/if}
    </div>
  </div>

  <div class="players-section">
    <ul class="events">
      {#each events as e}
        <li class={e.kind}>{eventText(e)}</li>
      {/each}
    </ul>

    <div class="list-fill"><ul class="k-list">
      {#each killer.players as p (p.name)}
        <li class:current-row={p.current} class:out={p.out} animate:flip={{ duration: 300 }}>
          <span class="row-name">
            <span class="swatch" style="{ringStyle(p)}"><Avatar name={p.name || ''} color={p.color} size={100} /></span>
            <span class="name">{shownName(p.name)}</span>
          </span>
          <span class="slot">
            {#if p.out}
              <span class="tag">{t('OUT')}</span>
            {:else if p.killer}
              <span class="tag killer">{t('KILLER')}</span>
            {:else if killer.phase === 'bull_off'}
              <span class="num">{p.bull_off_mm != null ? `${p.bull_off_mm} mm` : '—'}</span>
            {:else}
              <span class="num">{p.number ?? '—'}</span>
            {/if}
          </span>
          <span class="lives">{#if !p.out}<LivesDisplay lives={p.lives} {livesMax} />{/if}</span>
        </li>
      {/each}
    </ul></div>
  </div>
</div>

<div class="k-board">
  <DartBoard readonly darts={markers} zones={boardZones(killer)} />
  <button type="button" class="btn-cancel" onclick={stop}>{t('✕ Cancel')}</button>
</div>

{#if correctingIndex != null}
  <DartCorrectModal dartIndex={correctingIndex} onClose={() => (correctingIndex = null)}
                    endpoint="/api/killer/correct-dart" />
{/if}
{#if correctingLast}
  <DartCorrectModal dartIndex={0} onClose={() => (correctingLast = false)}
                    endpoint="/api/killer/correct-last-dart" />
{/if}

<style>
  .k-main { flex: 3 1 0; min-width: 0; display: flex; flex-direction: column; gap: 1.2vw; min-height: 0; }
  .player-card {
    flex: 0 0 21vw; display: flex; flex-direction: column; justify-content: space-between; gap: 1vw; border-radius: 24px; padding: 2vw 2.2vw 1.5vw;
    background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur);
  }
  .name-row { display: flex; align-items: center; justify-content: space-between; gap: 1.5vw; }
  .turn { display: flex; align-items: center; gap: 1vw; min-width: 0; }
  .turn .swatch { width: 1.5em; height: 1.5em; font-size: clamp(1.4rem, 3vw, 3rem); overflow: visible; }
  .turn-name { font-size: clamp(1.5rem, 3.5vw, 4rem); font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.1em; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .turn-hint { font-size: clamp(0.9rem, 1.8vw, 2rem); color: var(--yellow); font-weight: 700; text-align: right; }

  .darts-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1vw; align-items: stretch; min-height: 6.7vw; }
  .darts-row.single { grid-template-columns: 1fr; }
  .dart-box {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); border-radius: 16px;
    padding: 0.6vw 0.8vw; font-family: inherit; color: inherit; cursor: pointer;
    transition: border-color 0.15s, transform 0.15s, box-shadow 0.15s;
  }
  .dart-box:disabled { cursor: default; color: var(--muted); }
  .dart-box:not(:disabled):hover {
    border-color: var(--accent); transform: translateY(-2px);
    box-shadow: 0 8px 20px -10px color-mix(in srgb, var(--accent) 50%, transparent);
  }
  .dlabel { font-size: clamp(0.6rem, 0.9vw, 1rem); color: var(--muted); margin-bottom: 2px; }
  .dval { font-size: clamp(1.2rem, 2.5vw, 3rem); font-weight: 800; }
  .dsub { font-size: clamp(0.6rem, 0.9vw, 1rem); min-height: 1.2em; }
  .dart-box.miss .dval { color: var(--red); }

  .events { list-style: none; padding: 0; margin: 0; min-height: 3.2em; font-size: clamp(0.85rem, 1.4vw, 1.5rem); }
  .events li { padding: 0.12em 0; color: var(--muted); }
  .events li.killer, .events li.out { color: var(--red); font-weight: 700; }
  .events li.hit, .events li.own_goal { color: var(--yellow); font-weight: 700; }

  .endgame-row { display: flex; gap: 1vw; }
  .btn-end-game {
    background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2);
    border-radius: 999px; flex: 1; padding: 0.75rem 0.5rem; text-align: center; display: inline-flex; align-items: center; justify-content: center; gap: 0.5em;
    font-size: clamp(1rem, 1.5vw, 1.6rem); font-weight: 600; cursor: pointer;
    transition: border-color 0.15s, color 0.15s, transform 0.15s;
  }
  .btn-end-game:disabled { opacity: 0.35; cursor: default; }
  .btn-end-game:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); transform: translateY(-1px); }
  .btn-end-game.danger:hover:not(:disabled) { border-color: var(--red); color: var(--red); }
  .btn-end-game.start { border-color: var(--green); color: var(--green); }

  .players-section { flex: 1 1 0; overflow: hidden; display: flex; flex-direction: column; padding: 1.2vw 1.6vw; min-height: 0; border-radius: 24px; background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); }
  /* Absolutely placed, so the list never makes the card taller: it fills what the player card leaves and
     scrolls when there are more players. */
  .list-fill { position: relative; flex: 1; min-height: 0; }
  .k-list { list-style: none; padding: 0; margin: 0; position: absolute; inset: 0; overflow-y: auto; }
  .k-list li {
    display: grid; grid-template-columns: 1fr 5.5em auto; align-items: center; gap: 1vw;
    padding: 0.4vw 1vw; margin-top: 0.4vw; border-radius: 10px; min-height: 3.2vw;
    font-size: clamp(0.85rem, 1.5vw, 1.9rem); border: 1px solid transparent; transition: background 0.2s;
  }
  .k-list li:first-child { margin-top: 0; }
  .current-row {
    background: linear-gradient(90deg, color-mix(in srgb, var(--green) 14%, transparent), transparent);
    border-color: color-mix(in srgb, var(--green) 25%, transparent) !important;
  }
  .current-row .name { color: var(--green); font-weight: 700; }
  .k-list li.out { opacity: 0.45; }
  .k-list li.out .name { text-decoration: line-through; }
  .row-name { display: flex; align-items: center; gap: 0.7em; min-width: 0; }
  .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .swatch { width: 1.5em; height: 1.5em; border-radius: 50%; flex-shrink: 0; overflow: visible; }
  .slot { display: flex; justify-content: center; }
  .num { font-weight: 900; color: var(--muted); }
  .lives { display: flex; justify-content: flex-end; min-width: 3.2em; font-size: 0.8em; }
  .tag { font-size: 0.6em; font-weight: 800; letter-spacing: 0.04em; color: var(--muted); border: 1px solid var(--glass-border); border-radius: 999px; padding: 0 0.6em; white-space: nowrap; }
  .tag.killer { color: var(--red); border-color: color-mix(in srgb, var(--red) 55%, transparent); background: color-mix(in srgb, var(--red) 18%, rgba(0, 0, 0, 0.3)); }

  .k-board {
    position: relative; flex: 2 1 0; min-width: 0; display: flex; align-items: center; justify-content: center;
    padding: 1.5vw; border-radius: 24px; background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); --board-max: min(100%, 78vh);
  }
  .btn-cancel {
    position: absolute; bottom: 1.2vw; right: 1.4vw;
    background: var(--glass); border: 1px solid var(--glass-border); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2);
    border-radius: 999px; padding: 0.6rem 1.4rem; color: var(--muted); font-family: inherit; font-weight: 600;
    font-size: clamp(0.9rem, 1.2vw, 1.3rem); cursor: pointer; transition: border-color 0.15s, color 0.15s, background 0.15s;
  }
  .btn-cancel:hover { border-color: var(--red); color: var(--red); background: rgba(248, 113, 113, 0.08); }
  .swatch :global(svg) { width: 100%; height: 100%; }
</style>
