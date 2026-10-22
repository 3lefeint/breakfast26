<script>
  import { confirmDialog } from '../../lib/confirm.js';
  import { navigate } from '../../lib/router.js';
  import { t } from '../../lib/i18n.js';
  import Avatar from '../../lib/components/Avatar.svelte';
  // Live Field Training. The board fills most of the height with the darts of the turn in progress,
  // the field lit up (a number; the bull is named in the bar). Beside it: the darts of the turn
  // (tap one to correct it), the progress of the run, the points and the hit rate, and the last
  // turns. Finish ends the run early and keeps what was thrown as practice.
  import { api } from '../../lib/api.js';
  import { fieldLabel, finishRun, stopRun, undoTurn, percent } from '../../lib/fieldTraining.js';
  import Icon from '../../lib/components/Icon.svelte';
  import { gameState } from '../../lib/stores/gameState.js';
  import { isBoardStopped, shownName } from '../../lib/util.js';
  import DartBoard from '../../lib/components/DartBoard.svelte';
  import DartCorrectModal from './DartCorrectModal.svelte';

  let { ft } = $props();

  let isBull = $derived(ft.field === 25);
  let darts = $derived(ft.current_darts || []);
  let markers = $derived((ft.round_darts?.[ft.player] || []).map((d, i) => (
    { n: `${i}`, label: d.points, x: d.x, y: d.y, color: ft.color, avatar: { name: ft.player, color: ft.color } })));
  let progress = $derived(Math.min(100, (ft.thrown / ft.darts) * 100));
  let lastTurns = $derived([...(ft.turn_points || [])].slice(-8).reverse());
  // The turn counts only the darts that are left, the last one may have fewer than three.
  let slots = $derived(Math.min(3, ft.remaining));

  let correctingIndex = $state(null);

  function openCorrect(index) {
    if (ft.state !== 'playing') return;
    correctingIndex = index;
  }

  async function finish() {
    if (!await confirmDialog(ft.thrown ? t('End the run now and keep the darts thrown as practice?') : t('Cancel the run?'))) return;
    await finishRun();
    if (!ft.thrown) navigate('home');
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
    await api('POST', '/api/field-training/next');
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
        <span class="swatch"><Avatar name={ft.player || ''} color={ft.color} size={100} /></span>
        <span class="name">{shownName(ft.player)}</span>
        <span class="turn">{t('Turn {n}', { n: ft.turn })}</span>
      </div>
      <div class="target">
        <span class="target-label">{t('Field')}</span>
        <span class="target-value">{fieldLabel(ft.field)}</span>
      </div>
    </div>
    <div class="darts-row">
      {#each [0, 1, 2] as i}
        {#if i < slots}
          <button type="button" class="dart-box" class:miss={darts[i] === 0} class:empty={darts[i] == null}
                  disabled={ft.state !== 'playing'} onclick={() => openCorrect(i)}>
            <span class="dlabel">D{i + 1}</span>
            <span class="dval">{darts[i] ?? '—'}</span>
            <span class="dsub"></span>
          </button>
        {/if}
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
      <div class="progress">
        <div class="progress-line"><span class="progress-fill" style="width: {progress}%"></span></div>
        <div class="progress-text"><strong>{ft.thrown}</strong> {t('of {total} darts · {left} left', { total: ft.darts, left: ft.remaining })}</div>
      </div>

      <div class="stats">
        <div class="stat"><span class="value">{ft.points}</span><span class="label">{t('Points')}</span></div>
        <div class="stat"><span class="value">{percent(ft.hit_rate)}</span><span class="label">{t('Hit rate')}</span></div>
        <div class="stat"><span class="value">{ft.hits.singles}</span><span class="label">{isBull ? t('Outer') : t('Singles')}</span></div>
        <div class="stat"><span class="value">{ft.hits.doubles}</span><span class="label">{isBull ? t("Bull's eye") : t('Doubles')}</span></div>
        {#if !isBull}<div class="stat"><span class="value">{ft.hits.triples}</span><span class="label">{t('Triples')}</span></div>{/if}
      </div>

      <div class="last">
        <span class="last-label">{t('Last turns')}</span>
        {#each lastTurns as p}<span class="last-chip" class:zero={p === 0}>{p}</span>{/each}
        {#if !lastTurns.length}<span class="none">—</span>{/if}
      </div>
    </div></div>
  </div>
</div>

<div class="tv-board">
  <DartBoard readonly darts={markers} highlight={isBull ? null : ft.field} />
  <button type="button" class="btn-cancel" onclick={stop}>{t('✕ Cancel')}</button>
</div>

{#if correctingIndex != null}
  <DartCorrectModal dartIndex={correctingIndex} onClose={() => (correctingIndex = null)}
                    endpoint="/api/field-training/correct-dart" />
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

  .progress-line { height: clamp(8px, 1vw, 16px); background: rgba(255, 255, 255, 0.14); border-radius: 999px; overflow: hidden; }
  .progress-fill { display: block; height: 100%; background: var(--accent); border-radius: 999px; transition: width 0.3s; }
  .progress-text { margin-top: 0.4rem; color: var(--muted); font-size: clamp(0.9rem, 1.6vw, 1.6rem); }
  .progress-text strong { color: var(--text); }
  .stats { display: flex; flex-wrap: wrap; gap: 0.8vw; }
  .stat { flex: 1; min-width: 4.2em; display: flex; flex-direction: column; padding: 0.6vw 1vw; background: var(--glass); border: 1px solid var(--glass-border); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2); border-radius: 10px; }
  .value { font-size: clamp(1.2rem, 2.2vw, 2.6rem); font-weight: 900; white-space: nowrap; }
  .label { font-size: clamp(0.65rem, 1vw, 1rem); color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
  .last { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5vw; font-size: clamp(0.9rem, 1.5vw, 1.5rem); }
  .last-label { color: var(--muted); margin-right: 0.6vw; }
  .last-chip { min-width: 1.8em; text-align: center; padding: 0.1em 0.4em; border: 1px solid var(--glass-border); border-radius: 8px; font-weight: 700; }
  .last-chip.zero { color: var(--muted); }
  .none { color: var(--muted); }
</style>
