<script>
  // Ports tv.html's #activeElim: two-column layout (player card | scrollable
  // turn-queue list). Dart boxes are tap-to-correct, unlike Home's
  // plain DartsRow, so they're inlined here rather than reusing that
  // component. Reuses TargetDisplay/FreipassBadge/WinBadge/LivesDisplay
  // from Step 2/5 for the parts that are visually identical.
  import { cap } from '../../lib/util.js';
  import { api } from '../../lib/api.js';
  import { flip } from 'svelte/animate';
  import WinBadge from '../../lib/components/WinBadge.svelte';
  import LivesDisplay from '../../lib/components/LivesDisplay.svelte';
  import Crown from '../../lib/components/Crown.svelte';
  import DartBoard from '../../lib/components/DartBoard.svelte';
  import DartCorrectModal from './DartCorrectModal.svelte';
  import OnlineBanner from '../../lib/components/OnlineBanner.svelte';

  let { elimination, winsFor, boardDarts = null, online = null } = $props();

  let darts = $derived(elimination.current_darts || []);
  let total = $derived(darts.reduce((a, b) => a + b, 0));
  let turnOrder = $derived(elimination.turn_order || []);
  let livesMax = $derived(elimination.lives_max || 3);

  // Crown goes to whoever has the most Elimination wins — not a pill
  // badge on everyone (mockups/elimination_crown_mockups.png).
  let maxWins = $derived(Math.max(0, ...turnOrder.map((p) => winsFor(p.name))));
  function isTopWinner(name) {
    return maxWins > 0 && winsFor(name) === maxWins;
  }

  let correctingIndex = $state(null);

  function openCorrect(index) {
    if (elimination.state !== 'playing') return;
    if (darts[index] == null) return;
    if (online && online.match && online.match.owners[elimination.current_player] !== online.site) return;   // theirs
    correctingIndex = index;
  }

  async function stop() {
    if (!confirm(online ? 'Leave the online match?' : 'Stop the current game?')) return;
    await api('POST', '/api/elimination/stop');
    window.location.href = '/';
  }

  async function undo() {
    if (!confirm('Undo the last completed turn?')) return;
    await api('POST', '/api/elimination/undo');
  }
</script>

<div class="player-card">
  <OnlineBanner {online} currentPlayer={elimination.current_player} />
  <div class="player-name">{cap(elimination.current_player || '—')}</div>
  <div class="player-score">{total}</div>
  <div class="darts-row">
    {#each [0, 1, 2] as i}
      <button type="button" class="dart-box elim-dart-correctable" class:miss={darts[i] === 0} onclick={() => openCorrect(i)}>
        <div class="dlabel">D{i + 1}</div>
        <div class="dval">{darts[i] ?? '—'}</div>
      </button>
    {/each}
  </div>
  {#if boardDarts}
    <div class="live-board"><DartBoard readonly darts={boardDarts} /></div>
  {/if}
  <div class="elim-target-row">
    <span class="elim-target-label">Target</span>
    <span class="elim-target-value">{elimination.target != null ? elimination.target + 1 : '—'}</span>
  </div>
  <div class="freipass-badge-row">
    {#if elimination.freipass}
      <span class="freipass-badge">Freipass</span>
    {/if}
  </div>
  <div class="elim-endgame-row">
    {#if !online}<button class="btn-end-game" onclick={undo}>↩ Undo</button>{/if}
    <button class="btn-end-game" onclick={stop}>■ Stop</button>
  </div>
</div>

<div class="players-section">
  <ul class="tv-elim-list">
    {#each turnOrder as p (p.name)}
      <li class:elim-current-row={p.current} animate:flip={{ duration: 300 }}>
        <span class="elim-row-name">
          <span class="name-crown-wrap">
            {#if isTopWinner(p.name)}<Crown />{/if}
            {cap(p.name || '—')}
          </span>
          <WinBadge wins={winsFor(p.name)} />
        </span>
        <LivesDisplay lives={p.lives || 0} {livesMax} />
      </li>
    {/each}
  </ul>
</div>

{#if correctingIndex != null}
  <DartCorrectModal dartIndex={correctingIndex} onClose={() => (correctingIndex = null)} />
{/if}

<style>
  .player-card {
    flex: 0 0 34%; border-bottom: none; border-right: 1px solid var(--border);
    padding: 2.5vw 3vw 1.5vw;
    background: linear-gradient(165deg, color-mix(in srgb, var(--accent) 9%, transparent), transparent 60%);
  }
  .player-name { font-size: clamp(1.5rem, 3.5vw, 4rem); font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 0.2em; }
  .player-score {
    font-size: clamp(3rem, 9vw, 8rem); font-weight: 900; color: var(--green); line-height: 0.9; margin-bottom: 0.15em;
    text-shadow: 0 0 32px color-mix(in srgb, var(--green) 35%, transparent);
  }
  .darts-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1vw; align-items: center; }
  .dart-box {
    background: color-mix(in srgb, var(--surface) 70%, var(--bg));
    border: 1px solid var(--border); border-radius: 12px;
    padding: 0.6vw 0.8vw; text-align: center; font-family: inherit; color: inherit; cursor: pointer;
    transition: border-color 0.15s, transform 0.15s, box-shadow 0.15s;
  }
  .dart-box:hover {
    border-color: var(--accent);
    transform: translateY(-2px);
    box-shadow: 0 8px 20px -10px color-mix(in srgb, var(--accent) 50%, transparent);
  }
  .dart-box .dlabel { font-size: clamp(0.6rem, 0.9vw, 1rem); color: var(--muted); margin-bottom: 2px; }
  .dart-box .dval { font-size: clamp(1.2rem, 2.5vw, 3rem); font-weight: 800; }
  .dart-box.miss .dval { color: var(--red); }
  .live-board { --board-max: min(360px, 32vh); margin-top: 1rem; display: flex; justify-content: center; }
  .elim-target-row { display: flex; align-items: baseline; gap: 0.6em; margin-top: 1rem; }
  .elim-target-label { font-size: clamp(0.75rem, 1.3vw, 1.1rem); color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; }
  .elim-target-value {
    font-size: clamp(1.6rem, 3.8vw, 3rem); font-weight: 800; color: var(--accent);
    text-shadow: 0 0 28px color-mix(in srgb, var(--accent) 40%, transparent);
  }
  .freipass-badge-row { margin-top: 1rem; min-height: 1.6em; }
  .freipass-badge {
    font-size: clamp(0.7rem, 1.2vw, 1.3rem); font-weight: 700;
    background: color-mix(in srgb, var(--yellow) 18%, var(--surface));
    color: var(--yellow); border: 1px solid color-mix(in srgb, var(--yellow) 35%, transparent);
    border-radius: 999px; padding: 0.15em 0.7em;
  }
  .elim-endgame-row { margin-top: 1.5rem; display: flex; gap: 0.6rem; }
  .btn-end-game {
    background: var(--surface); border: 1px solid var(--border); color: var(--muted);
    border-radius: 999px; padding: 0.55rem 1.25rem;
    font-size: clamp(0.8rem, 1.3vw, 1rem); font-weight: 600; cursor: pointer;
    transition: border-color 0.15s, color 0.15s, background 0.15s;
  }
  .btn-end-game:hover { border-color: var(--red); color: var(--red); background: rgba(248, 113, 113, 0.08); }
  .players-section { flex: 1; overflow-y: auto; overflow-x: hidden; padding: 1.8em 2vw 1.5vw; min-height: 0; }
  .tv-elim-list { list-style: none; }
  .tv-elim-list li {
    display: flex; align-items: center; justify-content: space-between;
    padding: 0.7vw 1vw; margin-top: 1em; border-radius: 10px;
    font-size: clamp(0.85rem, 1.6vw, 2rem);
    transition: background 0.2s;
  }
  .tv-elim-list li:first-child { margin-top: 0; }
  .elim-current-row {
    color: var(--text);
    background: linear-gradient(90deg, color-mix(in srgb, var(--green) 14%, transparent), transparent);
    border: 1px solid color-mix(in srgb, var(--green) 25%, transparent);
  }
  .elim-current-row .elim-row-name { color: var(--green); font-weight: 700; }
  .name-crown-wrap { position: relative; display: inline-block; }
</style>
