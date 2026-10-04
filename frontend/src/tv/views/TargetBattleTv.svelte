<script>
  // Live Target Battle. The board is the stage: it fills most of the height, with every dart of
  // the round in the color of its player and the target's field lit up. A new round with a random
  // target starts with the wheel: a needle turns around the board and lands on the field of the
  // target. The number is chosen by the backend, the wheel only shows it, so a screen that is
  // opened in the middle of a round shows the result right away.
  // Beside the board: the players with their darts of this round and their total, and a table of
  // every round with its target and what each player scored in it.
  import { untrack, tick } from 'svelte';
  import { flip } from 'svelte/animate';
  import { cap } from '../../lib/util.js';
  import { api } from '../../lib/api.js';
  import { SEGMENT_ORDER } from '../../lib/dartboard.js';
  import { ranked, boardDarts, stopGame } from '../../lib/targetBattle.js';
  import DartBoard from '../../lib/components/DartBoard.svelte';
  import DartCorrectModal from './DartCorrectModal.svelte';

  let { tb } = $props();

  const SPIN_MS = 4200;

  let darts = $derived(tb.current_darts || []);
  let roundKey = $derived(`${tb.tiebreak ? 't' : 'r'}${tb.round}`);
  let rows = $derived(ranked(tb));
  let markers = $derived(boardDarts(tb));
  let roundLabel = $derived(tb.tiebreak ? `Tiebreak · round ${tb.round}` : `Round ${tb.round} of ${tb.rounds}`);
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
  // was opened just now (starting a game loads /tv), but not when it is opened in the middle of one.
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

  function openCorrect(p, index) {
    if (!p.current || tb.state !== 'playing' || darts[index] == null) return;
    correctingIndex = index;
  }

  async function stop() {
    if (!confirm('Stop the current game?')) return;
    await stopGame();
    window.location.href = '/';
  }

  async function undo() {
    if (!confirm('Undo the last completed turn?')) return;
    await api('POST', '/api/target-battle/undo');
  }

  function ringStyle(p) {
    return p.ring ? `outline: 3px ${p.ring.dash ? 'dashed' : 'solid'} ${p.ring.color}; outline-offset: 1px;` : '';
  }
</script>

<div class="stage">
  <div class="bar">
    <div class="round">
      <span class="round-label">{roundLabel}</span>
      {#if !tb.tiebreak}
        <span class="dots" aria-hidden="true">
          {#each Array(tb.rounds) as _, i}
            <span class="dot" class:done={i < tb.round - 1} class:now={i === tb.round - 1}></span>
          {/each}
        </span>
      {/if}
    </div>
    <div class="target">
      <span class="target-label">Target</span>
      <span class="target-value" class:spinning>{spinning ? '…' : tb.target}</span>
    </div>
  </div>

  <div class="body">
    <div class="board-col">
      <DartBoard readonly darts={markers} highlight={spinning ? null : tb.target} pointer={{ angle, ms }} />
    </div>

    <div class="side">
      <ul class="tb-list">
        {#each rows as p (p.name)}
          <li class:current-row={p.current} animate:flip={{ duration: 300 }}>
            <span class="row-name">
              <span class="swatch" style="background: {p.color || 'var(--muted)'}; {ringStyle(p)}"></span>
              <span class="name">{cap(p.name)}</span>
              {#if tb.tiebreak && !tb.contenders.includes(p.name)}<span class="out">out</span>{/if}
            </span>
            <span class="chips">
              {#each chips(p) as value, i}
                <button type="button" class="chip" class:live={p.current} class:miss={value === 0}
                        disabled={!p.current || value == null} onclick={() => openCorrect(p, i)}>
                  {value ?? '—'}
                </button>
              {/each}
            </span>
            <span class="total">{p.score}</span>
          </li>
        {/each}
      </ul>

      <div class="history" bind:this={tableBox}>
        <table>
          <thead>
            <tr>
              <th>Round</th><th>Target</th>
              {#each tb.order as name}
                <th class="who">{cap(name)}</th>
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

      <div class="endgame-row">
        <button class="btn-end-game" onclick={undo}>↩ Undo</button>
        <button class="btn-end-game" onclick={stop}>■ Stop</button>
      </div>
    </div>
  </div>
</div>

{#if correctingIndex != null}
  <DartCorrectModal dartIndex={correctingIndex} onClose={() => (correctingIndex = null)}
                    endpoint="/api/target-battle/correct-dart" />
{/if}

<style>
  .stage {
    flex: 1; min-width: 0; min-height: 0; display: flex; flex-direction: column;
    background: linear-gradient(165deg, color-mix(in srgb, var(--accent) 8%, transparent), transparent 55%);
  }
  .bar {
    display: flex; align-items: center; justify-content: space-between; gap: 2vw;
    padding: 1vw 3vw 0.4vw;
  }
  .round { display: flex; align-items: center; gap: 1.2vw; flex-wrap: wrap; }
  .round-label { font-size: clamp(0.9rem, 1.6vw, 1.6rem); color: var(--muted); font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; }
  .dots { display: flex; gap: 0.35vw; }
  .dot { width: clamp(8px, 0.9vw, 16px); height: clamp(8px, 0.9vw, 16px); border-radius: 50%; background: var(--border); }
  .dot.done { background: var(--accent); }
  .dot.now { background: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 30%, transparent); }
  .target { display: flex; align-items: baseline; gap: 0.8vw; }
  .target-label { font-size: clamp(0.8rem, 1.4vw, 1.4rem); color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; }
  .target-value {
    font-size: clamp(2.4rem, 6vw, 5.5rem); font-weight: 900; color: var(--accent); line-height: 1; min-width: 1.5em; text-align: right;
    text-shadow: 0 0 32px color-mix(in srgb, var(--accent) 45%, transparent);
  }
  .target-value.spinning { opacity: 0.6; }

  .body { flex: 1; min-height: 0; display: flex; gap: 2vw; padding: 0 2vw 1vw 2vw; }
  .board-col {
    flex: 1; min-width: 0; display: flex; align-items: center; justify-content: center;
    --board-max: min(calc(100vh - 215px), 60vw);
  }
  .side { flex: 0 0 clamp(340px, 36vw, 640px); min-height: 0; display: flex; flex-direction: column; gap: 1.2vw; }

  .tb-list { list-style: none; padding: 0; margin: 0; }
  .tb-list li {
    display: grid; grid-template-columns: 1fr auto auto; align-items: center; gap: 1.2vw;
    padding: 0.6vw 1vw; margin-top: 0.6vw; border-radius: 10px;
    font-size: clamp(0.9rem, 1.7vw, 2rem); border: 1px solid transparent; transition: background 0.2s;
  }
  .tb-list li:first-child { margin-top: 0; }
  .current-row {
    background: linear-gradient(90deg, color-mix(in srgb, var(--green) 14%, transparent), transparent);
    border-color: color-mix(in srgb, var(--green) 25%, transparent) !important;
  }
  .current-row .name { color: var(--green); font-weight: 700; }
  .row-name { display: flex; align-items: center; gap: 0.7em; min-width: 0; }
  .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .swatch { width: 0.9em; height: 0.9em; border-radius: 50%; flex-shrink: 0; }
  .out { font-size: 0.6em; color: var(--muted); border: 1px solid var(--border); border-radius: 999px; padding: 0 0.6em; }
  .chips { display: flex; gap: 0.4vw; }
  .chip {
    min-width: 2.1em; padding: 0.1em 0.3em; text-align: center; font-family: inherit; font-weight: 700; font-size: 0.8em;
    color: var(--muted); background: color-mix(in srgb, var(--surface) 70%, var(--bg)); border: 1px solid var(--border); border-radius: 8px;
  }
  .chip.live { color: var(--text); font-size: 1em; cursor: pointer; }
  .chip.live:not(:disabled):hover { border-color: var(--accent); }
  .chip.miss { color: var(--red); }
  .chip:disabled { cursor: default; }
  .total { font-weight: 900; min-width: 1.6em; text-align: right; font-size: 1.3em; }

  .history { flex: 1; min-height: 0; overflow-y: auto; border: 1px solid var(--border); border-radius: 12px; background: color-mix(in srgb, var(--surface) 60%, var(--bg)); }
  table { width: 100%; border-collapse: collapse; font-size: clamp(0.8rem, 1.3vw, 1.5rem); }
  th { position: sticky; top: 0; background: var(--surface); color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; font-size: 0.75em; padding: 0.5em 0.6em; text-align: center; }
  th.who { max-width: 6em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  td { padding: 0.35em 0.6em; text-align: center; border-top: 1px solid var(--border); }
  td.t { color: var(--accent); font-weight: 800; }
  td.zero { color: var(--muted); }
  tr.now td { background: color-mix(in srgb, var(--green) 10%, transparent); }

  .endgame-row { display: flex; gap: 0.6rem; }
  .btn-end-game {
    background: var(--surface); border: 1px solid var(--border); color: var(--muted);
    border-radius: 999px; padding: 0.55rem 1.25rem;
    font-size: clamp(0.8rem, 1.3vw, 1rem); font-weight: 600; cursor: pointer;
    transition: border-color 0.15s, color 0.15s, background 0.15s;
  }
  .btn-end-game:hover { border-color: var(--red); color: var(--red); background: rgba(248, 113, 113, 0.08); }
</style>
