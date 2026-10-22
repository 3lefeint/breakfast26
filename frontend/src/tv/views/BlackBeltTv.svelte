<script>
  import { confirmDialog } from '../../lib/confirm.js';
  import { navigate } from '../../lib/router.js';
  import { t } from '../../lib/i18n.js';
  import { api } from '../../lib/api.js';
  import Avatar from '../../lib/components/Avatar.svelte';
  // Live Black Belt. The board shows the darts of the turn with the double that is up lit; beside
  // it the darts of the turn (a hit is marked, tap one to correct it), the ladder, the darts the
  // field has left and the bonus darts in hand, and the counters of the run.
  import { stepLabel, finishRun, stopRun, undoTurn } from '../../lib/blackBelt.js';
  import Icon from '../../lib/components/Icon.svelte';
  import { gameState } from '../../lib/stores/gameState.js';
  import { isBoardStopped, shownName } from '../../lib/util.js';
  import DartBoard from '../../lib/components/DartBoard.svelte';
  import BlackBeltLadder from '../../lib/components/BlackBeltLadder.svelte';
  import DartCorrectModal from './DartCorrectModal.svelte';

  let { bb } = $props();

  let darts = $derived(bb.current_darts || []);
  let markers = $derived((bb.round_darts?.[bb.player] || []).map((d, i) => (
    { n: `${i}`, label: d.hit ? '✓' : '', x: d.x, y: d.y, color: bb.color, avatar: { name: bb.player, color: bb.color } })));
  let zones = $derived(bb.target === 25 ? [] : [{ n: bb.target, parts: ['double'], level: 'strong' }]);
  let attempt = $derived((bb.attempts?.length || 0) + 1);

  let correctingIndex = $state(null);

  function openCorrect(index) {
    if (bb.state !== 'playing') return;
    correctingIndex = index;
  }

  async function finish() {
    if (!await confirmDialog(bb.thrown ? t('End the run now and keep the darts thrown?') : t('Cancel the run?'))) return;
    await finishRun();
    if (!bb.thrown) navigate('home');
  }

  async function stop() {
    if (!await confirmDialog(t('Cancel the run without keeping it?'))) return;
    await stopRun();
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
    await api('POST', '/api/black-belt/next');
  }

  async function undo() {
    if (!await confirmDialog(t('Undo the last completed turn?'))) return;
    await undoTurn();
  }
</script>

<div class="tv-main">
  <div class="player-card">
    <div class="name-row">
      <div class="who">
        <span class="swatch"><Avatar name={bb.player || ''} color={bb.color} size={100} /></span>
        <span class="name">{shownName(bb.player)}</span>
        <span class="turn">{t('Attempt {n}', { n: attempt })}{bb.backwards ? ' · ' + t('backwards') : ''}</span>
      </div>
      <div class="target">
        <span class="target-label">{t('Up')}</span>
        <span class="target-value">{stepLabel(bb.target)}</span>
      </div>
    </div>
    <div class="darts-row">
      {#each [0, 1, 2] as i}
        <button type="button" class="dart-box" class:hit={darts[i]?.hit} class:miss={darts[i] && !darts[i].hit}
                class:empty={darts[i] == null} disabled={bb.state !== 'playing'} onclick={() => openCorrect(i)}>
          <span class="dlabel">D{i + 1}</span>
          <span class="dval">{#if darts[i]}{stepLabel(darts[i].field)}{:else}—{/if}</span>
          <span class="dsub"></span>
          {#if darts[i]?.hit}<span class="tick">✓</span>{/if}
        </button>
      {/each}
    </div>
      <div class="endgame-row">
        <button class="btn-end-game" onclick={undo}>{t('↩ Undo')}</button>
        <button class="btn-end-game" onclick={nextTurn}>{t('⏭ Next')}</button>
        {#if boardStopped}
          <button class="btn-end-game start" disabled={!$gameState.has_cloud_control} onclick={startBoard}><Icon name="board" size={20} />{t('Start')}</button>
        {:else}
          <button class="btn-end-game danger" disabled={!$gameState.has_cloud_control} onclick={resetBoard}><Icon name="board" size={20} />{t('Reset')}</button>
        {/if}
        <button class="btn-end-game" onclick={finish}>{t('⏹ Finish')}</button>
      </div>
  </div>

  <div class="players-section">
    <div class="fill"><div class="scroll">
      <div class="hand">
        {#if bb.bonus_darts > 0}
          <span class="bonus">{bb.bonus_darts === 1 ? t('{n} bonus dart in hand', { n: bb.bonus_darts }) : t('{n} bonus darts in hand', { n: bb.bonus_darts })}</span>
        {/if}
        <span class="own">{bb.own_left === 1 ? t('{n} dart of its own left at {field}', { n: bb.own_left, field: stepLabel(bb.target) }) : t('{n} darts of its own left at {field}', { n: bb.own_left, field: stepLabel(bb.target) })}</span>
      </div>

      <BlackBeltLadder steps={bb.steps} position={bb.position} belt={bb.belt} />

      <div class="stats">
        <div class="stat"><span class="value">{bb.position}</span><span class="label">{t('Done')}</span></div>
        <div class="stat"><span class="value">{bb.furthest}</span><span class="label">{t('Furthest')}</span></div>
        <div class="stat"><span class="value">{bb.restarts}</span><span class="label">{t('Restarts')}</span></div>
        <div class="stat"><span class="value">{bb.thrown}</span><span class="label">{t('Darts')}</span></div>
      </div>
    </div></div>
  </div>
</div>

<div class="tv-board">
  <DartBoard readonly darts={markers} {zones} />
  <button type="button" class="btn-cancel" onclick={stop}>{t('✕ Cancel')}</button>
</div>

{#if correctingIndex != null}
  <DartCorrectModal dartIndex={correctingIndex} onClose={() => (correctingIndex = null)}
                    endpoint="/api/black-belt/correct-dart" />
{/if}

<style>
  .tv-main { flex: 3 1 0; min-width: 0; display: flex; flex-direction: column; gap: 1.2vw; min-height: 0; }
  .player-card {
    flex: 0 0 21vw; display: flex; flex-direction: column; justify-content: space-between; gap: 1vw; border-radius: 24px; padding: 2vw 2.2vw 1.5vw;
    background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur);
  }
  .name-row { display: flex; align-items: center; justify-content: space-between; gap: 1.5vw; }
  .who { display: flex; align-items: center; gap: 1vw; min-width: 0; flex-wrap: wrap; }
  .swatch { width: 1.5em; height: 1.5em; font-size: clamp(1.4rem, 3vw, 3rem); border-radius: 50%; flex-shrink: 0; overflow: visible; }
  .swatch :global(svg) { width: 100%; height: 100%; }
  .name { font-size: clamp(1.5rem, 3.5vw, 4rem); font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.1em; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .turn { font-size: clamp(0.8rem, 1.4vw, 1.4rem); color: var(--muted); font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; }
  .target { display: flex; align-items: baseline; gap: 0.6em; flex-shrink: 0; }
  .target-label { font-size: clamp(0.75rem, 1.3vw, 1.1rem); color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; }
  .target-value { font-size: clamp(1.6rem, 3.4vw, 4rem); font-weight: 800; color: var(--accent); text-shadow: 0 0 28px color-mix(in srgb, var(--accent) 40%, transparent); }

  .darts-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1vw; align-items: stretch; min-height: 6.7vw; }
  .dart-box {
    position: relative; display: flex; flex-direction: column; align-items: center; justify-content: center;
    background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); border-radius: 16px;
    padding: 0.6vw 0.8vw; font-family: inherit; color: inherit; cursor: pointer;
    transition: border-color 0.15s, transform 0.15s, box-shadow 0.15s;
  }
  .dart-box:disabled { cursor: default; }
  .dart-box:not(:disabled):hover {
    border-color: var(--accent); transform: translateY(-2px);
    box-shadow: 0 8px 20px -10px color-mix(in srgb, var(--accent) 50%, transparent);
  }
  .dlabel { font-size: clamp(0.6rem, 0.9vw, 1rem); color: var(--muted); margin-bottom: 2px; }
  .dval { font-size: clamp(1.2rem, 2.5vw, 3rem); font-weight: 800; }
  .dart-box.hit { border-color: var(--green); }
  .dart-box.hit .dval { color: var(--green); }
  .dsub { font-size: clamp(0.6rem, 0.9vw, 1rem); min-height: 1.2em; }
  .dart-box.miss .dval { color: var(--red); }
  .dart-box.empty .dval { color: var(--muted); }
  .tick { position: absolute; top: 0.3em; right: 0.6em; font-size: clamp(0.7rem, 1.1vw, 1.2rem); color: var(--green); }

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
  /* Absolutely placed, so the content never makes the card taller: it fills what the player card leaves and
     scrolls when it is longer. */
  .fill { position: relative; flex: 1; min-height: 0; }
  .scroll { position: absolute; inset: 0; overflow-y: auto; display: flex; flex-direction: column; justify-content: center; gap: 1.4vw; }

  .tv-board {
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

  .hand { display: flex; flex-direction: column; gap: 0.2em; color: var(--muted); }
  .bonus { color: var(--accent); font-weight: 700; }
  .stats { display: flex; flex-wrap: wrap; gap: 0.8vw; }
  .stat { flex: 1; min-width: 4.5em; display: flex; flex-direction: column; padding: 0.6vw 1vw; background: var(--glass); border: 1px solid var(--glass-border); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2); border-radius: 10px; }
  .value { font-size: clamp(1.2rem, 2.2vw, 2.6rem); font-weight: 900; white-space: nowrap; }
  .label { font-size: clamp(0.65rem, 1vw, 1rem); color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
</style>
