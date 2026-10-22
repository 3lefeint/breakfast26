<script>
  import { confirmDialog } from '../../lib/confirm.js';
  import { navigate } from '../../lib/router.js';
  import { t } from '../../lib/i18n.js';
  import Avatar from '../../lib/components/Avatar.svelte';
  // Live Target Battle. The board is the stage: it fills most of the height, with every dart of
  // the round in the color of its player and the target's field lit up. A new round with a random
  // target starts with the wheel: a needle turns around the board and lands on the field of the
  // target. The number is chosen by the backend, the wheel only shows it, so a screen that is
  // opened in the middle of a round shows the result right away.
  // Beside the board: the players with their darts of this round and their total, and a table of
  // every round with its target and what each player scored in it.
  import { untrack, tick } from 'svelte';
  import { flip } from 'svelte/animate';
  import { shownName, isBoardStopped } from '../../lib/util.js';
  import { api } from '../../lib/api.js';
  import { SEGMENT_ORDER } from '../../lib/dartboard.js';
  import { ranked, boardDarts, stopGame } from '../../lib/targetBattle.js';
  import Icon from '../../lib/components/Icon.svelte';
  import { gameState } from '../../lib/stores/gameState.js';
  import DartBoard from '../../lib/components/DartBoard.svelte';
  import DartCorrectModal from './DartCorrectModal.svelte';

  let { tb } = $props();

  const SPIN_MS = 4200;

  let darts = $derived(tb.current_darts || []);
  let roundKey = $derived(`${tb.tiebreak ? 't' : 'r'}${tb.round}`);
  let rows = $derived(ranked(tb));
  let markers = $derived(boardDarts(tb));
  let me = $derived(rows.find((p) => p.current) || null);
  let total = $derived(darts.reduce((a, b) => a + b, 0));
  let history = $derived(tb.history || []);

  // The three darts of a player in this round: the live ones for whoever is up, the thrown ones for
  // those who are done, dashes for those who have not played yet.
  function chips(p) {
    const values = p.current ? darts : (tb.round_darts?.[p.name] || []).map((d) => d.points);
    return [0, 1, 2].map((i) => values[i] ?? null);
  }

  let angle = $state(0);
  let ms = $state(0);
  let spinning = $state(false);

  // The wheel turns for a round that is only seconds old, once per round: also when this screen
  // was opened just now (starting a game opens the TV view), but not when it is opened in the middle of one.
  const FRESH_S = 3;
  let spunKey = null;
  let timer = null;

  $effect(() => {
    const key = roundKey;
    const target = tb.target;
    const turns = tb.wheel && tb.round_age < FRESH_S && key !== spunKey;
    untrack(() => {
      const landing = SEGMENT_ORDER.indexOf(target) * 18;
      if (turns) {
        clearTimeout(timer);
        const to = Math.ceil(angle / 360) * 360 + 360 * 4 + landing;
        spinning = true;
        spunKey = key;
        // Two frames later, so the browser has painted the needle where it is and has a start for the turn.
        requestAnimationFrame(() => requestAnimationFrame(() => { ms = SPIN_MS; angle = to; }));
        timer = setTimeout(() => { spinning = false; }, SPIN_MS + 300);
      } else if (!spinning) {
        ms = 0;
        angle = landing;
      }
    });
  });

  // Keep the round in progress in view when the table is longer than the screen.
  let tableBox = $state(null);
  $effect(() => {
    history.length;
    tick().then(() => tableBox?.querySelector('tr.now')?.scrollIntoView({ block: 'nearest' }));
  });

  let correctingIndex = $state(null);

  function openCorrect(index) {
    if (tb.state !== 'playing') return;
    correctingIndex = index;
  }

  async function stop() {
    if (!await confirmDialog(t('Cancel the current game?'))) return;
    await stopGame();
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
    await api('POST', '/api/target-battle/next');
  }

  async function undo() {
    if (!await confirmDialog(t('Undo the last completed turn?'))) return;
    await api('POST', '/api/target-battle/undo');
  }

  function ringStyle(p) {
    return p.ring ? `outline: 3px ${p.ring.dash ? 'dashed' : 'solid'} ${p.ring.color}; outline-offset: 1px;` : '';
  }
</script>

<div class="tb-main">
  <div class="player-card">
    <div class="name-row">
      <div class="turn">
        <span class="swatch" style="{me ? ringStyle(me) : ''}"><Avatar name={me?.name || ''} color={me?.color} size={100} /></span>
        <span class="turn-name">{shownName(me?.name || '—')}</span>
      </div>
      <div class="target">
        <span class="target-label">{t('Target')}</span>
        <span class="target-value" class:spinning>{spinning ? '…' : tb.target}</span>
      </div>
    </div>
    <div class="darts-row">
      {#each [0, 1, 2] as i}
        <button type="button" class="dart-box" class:miss={darts[i] === 0}
                disabled={tb.state !== 'playing'} onclick={() => openCorrect(i)}>
          <span class="dlabel">D{i + 1}</span>
          <span class="dval">{darts[i] ?? '—'}</span>
          <span class="dsub"></span>
        </button>
      {/each}
      <div class="rest-col">{total}</div>
    </div>
    <div class="endgame-row">
      <button class="btn-end-game" onclick={undo}>{t('↩ Undo')}</button>
      <button class="btn-end-game" onclick={nextTurn}>{t('⏭ Next')}</button>
      {#if boardStopped}
        <button class="btn-end-game start" disabled={!$gameState.has_cloud_control} onclick={startBoard}><Icon name="board" size={20} />{t('Start')}</button>
      {:else}
        <button class="btn-end-game danger" disabled={!$gameState.has_cloud_control} onclick={resetBoard}><Icon name="board" size={20} />{t('Reset')}</button>
      {/if}
    </div>
  </div>

  <div class="players-section">
    <!-- The list is as high as its rows, up to 68% of the box; the table below takes what is left. -->
    <div class="fill" style="flex: 0 1 min({rows.length * 3.6}vw, 68%)"><ul class="tb-list scroll">
      {#each rows as p (p.name)}
        <li class:current-row={p.current} animate:flip={{ duration: 300 }}>
          <span class="row-name">
            <span class="swatch" style="{ringStyle(p)}"><Avatar name={p.name || ''} color={p.color} size={100} /></span>
            <span class="name">{shownName(p.name)}</span>
            {#if tb.tiebreak && !tb.contenders.includes(p.name)}<span class="out">{t('out')}</span>{/if}
          </span>
          <span class="chips">
            {#each chips(p) as value}
              <span class="chip" class:live={p.current} class:miss={value === 0}>{value ?? '—'}</span>
            {/each}
          </span>
          <span class="total">{p.score}</span>
        </li>
      {/each}
    </ul></div>

    <div class="fill history">
      <div class="scroll" bind:this={tableBox}>
        <table>
          <thead>
            <tr>
              <th>{t('Round')}</th><th>{t('Target')}</th>
              {#each tb.order as name}
                <th class="who">{shownName(name)}</th>
              {/each}
            </tr>
          </thead>
          <tbody>
            {#each history as r (`${r.tiebreak ? 't' : 'r'}${r.round}`)}
              <tr class:now={r.current}>
                <td>{r.tiebreak ? `T${r.round}` : r.round}</td>
                <td class="t">{r.target}</td>
                {#each tb.order as name}
                  <td class:zero={r.scores[name] === 0}>{r.scores[name] ?? '—'}</td>
                {/each}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<div class="tb-board">
  <DartBoard readonly darts={markers} highlight={spinning ? null : tb.target} pointer={{ angle, ms }} />
  <button type="button" class="btn-cancel" onclick={stop}>{t('✕ Cancel')}</button>
</div>

{#if correctingIndex != null}
  <DartCorrectModal dartIndex={correctingIndex} onClose={() => (correctingIndex = null)}
                    endpoint="/api/target-battle/correct-dart" />
{/if}

<style>
  .tb-main { flex: 3 1 0; min-width: 0; display: flex; flex-direction: column; gap: 1.2vw; min-height: 0; }
  .player-card {
    flex: 0 0 21vw; display: flex; flex-direction: column; justify-content: space-between; gap: 1vw; border-radius: 24px; padding: 2vw 2.2vw 1.5vw;
    background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur);
  }
  .name-row { display: flex; align-items: center; justify-content: space-between; gap: 1.5vw; }
  .turn { display: flex; align-items: center; gap: 1vw; min-width: 0; }
  .turn .swatch { width: 1.5em; height: 1.5em; font-size: clamp(1.4rem, 3vw, 3rem); overflow: visible; }
  .turn-name { font-size: clamp(1.5rem, 3.5vw, 4rem); font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.1em; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .target { display: flex; align-items: baseline; gap: 0.6em; flex-shrink: 0; }
  .target-label { font-size: clamp(0.75rem, 1.3vw, 1.1rem); color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; }
  .target-value {
    font-size: clamp(1.6rem, 3.4vw, 4rem); font-weight: 800; color: var(--accent); min-width: 1.5em; text-align: right;
    text-shadow: 0 0 28px color-mix(in srgb, var(--accent) 40%, transparent);
  }
  .target-value.spinning { opacity: 0.6; }

  .darts-row { display: grid; --rest-fs: clamp(3rem, 7vw, 8rem); grid-template-columns: 1fr 1fr 1fr calc(var(--rest-fs) * 2.1); gap: 1vw; align-items: stretch; min-height: 6.7vw; }
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
  /* Fixed width for three digits, so the dart boxes do not move when the total gets shorter. */
  .rest-col {
    align-self: center;
    font-size: var(--rest-fs); font-weight: 900; color: var(--green); line-height: 1; text-align: right; font-variant-numeric: tabular-nums;
    text-shadow: 0 0 32px color-mix(in srgb, var(--green) 35%, transparent);
  }

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

  .players-section { flex: 1 1 0; overflow: hidden; display: flex; flex-direction: column; gap: 1vw; padding: 1.2vw 1.6vw; min-height: 0; border-radius: 24px; background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); }
  /* Absolutely placed, so the list and the table never make the card taller: each fills its half of the
     box and scrolls on its own. */
  .fill { position: relative; flex: 1 1 0; min-height: 0; }
  .scroll { position: absolute; inset: 0; overflow-y: auto; }

  .tb-list { list-style: none; padding: 0; margin: 0; }
  .tb-list li {
    display: grid; grid-template-columns: 1fr auto auto; align-items: center; gap: 1.2vw;
    padding: 0.4vw 1vw; margin-top: 0.4vw; border-radius: 10px; min-height: 3.2vw;
    font-size: clamp(0.85rem, 1.5vw, 1.9rem); border: 1px solid transparent; transition: background 0.2s;
  }
  .tb-list li:first-child { margin-top: 0; }
  .current-row {
    background: linear-gradient(90deg, color-mix(in srgb, var(--green) 14%, transparent), transparent);
    border-color: color-mix(in srgb, var(--green) 25%, transparent) !important;
  }
  .current-row .name { color: var(--green); font-weight: 700; }
  .row-name { display: flex; align-items: center; gap: 0.7em; min-width: 0; }
  .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .swatch { width: 1.5em; height: 1.5em; border-radius: 50%; flex-shrink: 0; overflow: visible; }
  .out { font-size: 0.6em; color: var(--muted); border: 1px solid var(--glass-border); border-radius: 999px; padding: 0 0.6em; }
  .chips { display: flex; gap: 0.4vw; }
  .chip {
    min-width: 2.1em; padding: 0.1em 0.3em; text-align: center; font-weight: 700; font-size: 0.8em;
    color: var(--muted); background: var(--glass); border: 1px solid var(--glass-border); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2); border-radius: 8px;
  }
  .chip.live { color: var(--text); }
  .chip.miss { color: var(--red); }
  .total { font-weight: 900; min-width: 1.6em; text-align: right; font-size: 1.3em; }

  .history { border: 1px solid var(--glass-border); border-radius: 12px; background: rgba(0, 0, 0, 0.22); }
  table { width: 100%; border-collapse: collapse; font-size: clamp(0.8rem, 1.2vw, 1.4rem); }
  th { position: sticky; top: 0; background: color-mix(in srgb, var(--aurora-base) 85%, transparent); color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; font-size: 0.75em; padding: 0.5em 0.6em; text-align: center; }
  th.who { max-width: 6em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  td { padding: 0.3em 0.6em; text-align: center; border-top: 1px solid var(--glass-border); }
  td.t { color: var(--accent); font-weight: 800; }
  td.zero { color: var(--muted); }
  tr.now td { background: color-mix(in srgb, var(--green) 10%, transparent); }

  .tb-board {
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
