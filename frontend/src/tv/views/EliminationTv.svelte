<script>
  import { confirmDialog } from '../../lib/confirm.js';
  import { navigate } from '../../lib/router.js';
  import { t } from '../../lib/i18n.js';
  // Ports #activeElim of the former tv.html: two-column layout (player card | scrollable
  // turn-queue list). Dart boxes are tap-to-correct, unlike Home's
  // plain DartsRow, so they're inlined here rather than reusing that
  // component. Reuses TargetDisplay/FreipassBadge/WinBadge/LivesDisplay
  // from Step 2/5 for the parts that are visually identical.
  import { shownName, isBoardStopped } from '../../lib/util.js';
  import { api } from '../../lib/api.js';
  import { flip } from 'svelte/animate';
  import WinBadge from '../../lib/components/WinBadge.svelte';
  import LivesDisplay from '../../lib/components/LivesDisplay.svelte';
  import Crown from '../../lib/components/Crown.svelte';
  import Avatar from '../../lib/components/Avatar.svelte';
  import { gameState } from '../../lib/stores/gameState.js';
  import Icon from '../../lib/components/Icon.svelte';
  import DartBoard from '../../lib/components/DartBoard.svelte';
  import { beatZones } from '../../lib/dartboard.js';
  import DartCorrectModal from './DartCorrectModal.svelte';
  import OnlineBanner from '../../lib/components/OnlineBanner.svelte';

  let { elimination, winsFor, boardDarts = [], online = null } = $props();

  let darts = $derived(elimination.current_darts || []);
  let fields = $derived(elimination.current_fields || []);
  let total = $derived(darts.reduce((a, b) => a + b, 0));
  let turnOrder = $derived(elimination.turn_order || []);
  let livesMax = $derived(elimination.lives_max || 3);

  // Crown goes to whoever has the most Elimination wins — not a pill
  // badge on everyone (mockups/elimination_crown_mockups.png).
  let maxWins = $derived(Math.max(0, ...turnOrder.map((p) => winsFor(p.name))));
  function isTopWinner(name) {
    return maxWins > 0 && winsFor(name) === maxWins;
  }

  // The fields that still beat the target, if the hint is on: what is left of the target after the
  // darts of this turn. Nothing during the freipass, once the target is beaten or after the third dart.
  let beatHint = $derived($gameState.elimination_beat_hint === true);
  let beatRest = $derived(elimination.target != null ? elimination.target - total : null);
  let hintZones = $derived(
    beatHint && elimination.state === 'playing' && !elimination.freipass && darts.length < 3 && beatRest != null
      ? beatZones(beatRest) : []);

  async function toggleHint() {
    await api('PATCH', '/api/config', { web: { elimination_beat_hint: !beatHint } });
  }

  let correctingIndex = $state(null);

  function openCorrect(index) {
    if (elimination.state !== 'playing') return;
    if (online && online.match && online.match.owners[elimination.current_player] !== online.site) return;   // theirs
    correctingIndex = index;
  }

  async function stop() {
    if (!await confirmDialog(online ? t('Leave the online match?') : t('Cancel the current game?'))) return;
    await api('POST', '/api/elimination/stop');
    navigate('home');
  }

  // Ends the turn by hand, like pulling the darts.
  async function nextTurn() {
    await api('POST', '/api/elimination/next');
  }

  async function resetBoard() {
    await api('POST', '/api/control/reset-board');
  }

  // The board stopped (camera standby): Start brings it back, until then there is nothing to reset.
  let boardStopped = $derived(isBoardStopped($gameState.game?.board_status));

  async function startBoard() {
    await api('POST', '/api/control/start-board');
  }

  async function undo() {
    if (!await confirmDialog(t('Undo the last completed turn?'))) return;
    await api('POST', '/api/elimination/undo');
  }
</script>

<div class="elim-main">
<div class="player-card">
  <OnlineBanner {online} currentPlayer={elimination.current_player} />
  <div class="name-row">
    <div class="who">
      <span class="swatch"><Avatar name={elimination.current_player || ''} color={$gameState.player_colors?.[elimination.current_player] || null} size={100} /></span>
      <div class="player-name">{shownName(elimination.current_player || '—')}</div>
    </div>
    <div class="elim-target-row">
      {#if elimination.freipass}
        <span class="freipass-badge">{t('Freipass')}</span>
      {:else}
        <span class="elim-target-label">{t('Target')}</span>
        <span class="elim-target-value">{elimination.target != null ? elimination.target + 1 : '—'}</span>
      {/if}
    </div>
  </div>
  <div class="darts-row">
    {#each [0, 1, 2] as i}
      <button type="button" class="dart-box elim-dart-correctable" class:miss={darts[i] === 0} onclick={() => openCorrect(i)}>
        <div class="dlabel">D{i + 1}</div>
        <div class="dval">{darts[i] == null ? '—' : fields[i] ? String(fields[i]).toUpperCase() : t('Miss')}</div>
        <div class="dsub">{darts[i] != null ? `(${darts[i]})` : ''}</div>
      </button>
    {/each}
    <div class="rest-col">{total}</div>
  </div>
  <div class="elim-endgame-row">
    {#if !online}<button class="btn-end-game" onclick={undo}>{t('↩ Undo')}</button>{/if}
    <button class="btn-end-game" onclick={nextTurn}>{t('⏭ Next')}</button>
    {#if boardStopped}
      <button class="btn-end-game start" disabled={!$gameState.has_cloud_control} onclick={startBoard}><Icon name="board" size={20} />{t('Start')}</button>
    {:else}
      <button class="btn-end-game danger" disabled={!$gameState.has_cloud_control} onclick={resetBoard}><Icon name="board" size={20} />{t('Reset')}</button>
    {/if}
  </div>
</div>

<div class="players-section">
  <div class="list-fill"><ul class="tv-elim-list">
    {#each turnOrder as p (p.name)}
      <li class:elim-current-row={p.current} animate:flip={{ duration: 300 }}>
        <span class="row-avatar"><Avatar name={p.name || ''} color={$gameState.player_colors?.[p.name] || null} size={100} /></span>
        <span class="name-crown-wrap">
          {#if isTopWinner(p.name)}<Crown />{/if}
          {shownName(p.name || '—')}
        </span>
        <span class="row-wins"><WinBadge wins={winsFor(p.name)} /></span>
        <span class="row-lives"><LivesDisplay lives={p.lives || 0} {livesMax} /></span>
      </li>
    {/each}
  </ul></div>
</div>
</div>
<div class="elim-board">
  <button class="btn-end-game btn-hint" class:on={beatHint} aria-pressed={beatHint} onclick={toggleHint}>{t('◎ Hint')}</button>
  <DartBoard readonly darts={boardDarts} zones={hintZones} />
  <button type="button" class="btn-cancel" onclick={stop}>{t('✕ Cancel')}</button>
</div>

{#if correctingIndex != null}
  <DartCorrectModal dartIndex={correctingIndex} onClose={() => (correctingIndex = null)} />
{/if}

<style>
  .player-card {
    flex: 0 0 21vw; display: flex; flex-direction: column; justify-content: space-between; gap: 1vw; border-radius: 24px; padding: 2vw 2.2vw 1.5vw;
    background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur);
  }
  .name-row { display: flex; align-items: center; justify-content: space-between; gap: 1.5vw; }
  .who { display: flex; align-items: center; gap: 1vw; min-width: 0; }
  .swatch { width: 1.5em; height: 1.5em; font-size: clamp(1.4rem, 3vw, 3rem); border-radius: 50%; flex-shrink: 0; overflow: visible; }
  .swatch :global(svg) { width: 100%; height: 100%; }
  .player-name { font-size: clamp(1.5rem, 3.5vw, 4rem); font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.1em; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  /* Fixed width for three digits, so the dart boxes do not move when the total gets shorter. */
  .rest-col {
    align-self: center;
    font-size: var(--rest-fs); font-weight: 900; color: var(--green); line-height: 1; text-align: right; font-variant-numeric: tabular-nums;
    text-shadow: 0 0 32px color-mix(in srgb, var(--green) 35%, transparent);
  }
  .darts-row { display: grid; --rest-fs: clamp(3rem, 7vw, 8rem); grid-template-columns: 1fr 1fr 1fr calc(var(--rest-fs) * 2.1); gap: 1vw; align-items: stretch; min-height: 6.7vw; }
  .dart-box {
    background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); border-radius: 16px;
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
  .dart-box .dsub { font-size: clamp(0.6rem, 0.9vw, 1rem); color: var(--muted); min-height: 1.2em; }
  .dart-box.miss .dval { color: var(--red); }
  .elim-main { flex: 3 1 0; min-width: 0; display: flex; flex-direction: column; gap: 1.2vw; min-height: 0; }
  .elim-board {
    position: relative; flex: 2 1 0; min-width: 0; display: flex; align-items: center; justify-content: center;
    padding: 1.5vw; border-radius: 24px; background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); --board-max: min(100%, 78vh);
  }
  .elim-target-row { display: flex; align-items: baseline; gap: 0.6em; flex-shrink: 0; }
  .elim-target-label { font-size: clamp(0.75rem, 1.3vw, 1.1rem); color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; }
  .elim-target-value {
    font-size: clamp(1.6rem, 3.4vw, 4rem); font-weight: 800; color: var(--accent);
    text-shadow: 0 0 28px color-mix(in srgb, var(--accent) 40%, transparent);
  }
  .freipass-badge {
    font-size: clamp(1.4rem, 3vw, 3.4rem); font-weight: 800; align-self: center;
    background: color-mix(in srgb, var(--yellow) 18%, rgba(0, 0, 0, 0.3));
    color: var(--yellow); border: 1px solid color-mix(in srgb, var(--yellow) 35%, transparent);
    border-radius: 999px; padding: 0.1em 0.8em;
  }
  .elim-endgame-row { display: flex; gap: 1vw; }
  .btn-end-game {
    background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2);
    border-radius: 999px; flex: 1; padding: 0.75rem 0.5rem; text-align: center; display: inline-flex; align-items: center; justify-content: center; gap: 0.5em;
    font-size: clamp(1rem, 1.5vw, 1.6rem); font-weight: 600; cursor: pointer;
    transition: border-color 0.15s, color 0.15s, background 0.15s;
  }
  .btn-cancel {
    position: absolute; bottom: 1.2vw; right: 1.4vw;
    background: var(--glass); border: 1px solid var(--glass-border); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2);
    border-radius: 999px; padding: 0.6rem 1.4rem; color: var(--muted); font-family: inherit; font-weight: 600;
    font-size: clamp(0.9rem, 1.2vw, 1.3rem); cursor: pointer; transition: border-color 0.15s, color 0.15s, background 0.15s;
  }
  .btn-cancel:hover { border-color: var(--red); color: var(--red); background: rgba(248, 113, 113, 0.08); }
  .btn-hint { position: absolute; top: 1.2vw; right: 1.2vw; flex: none; padding: 0.75rem 1.4rem; }
  .btn-end-game:disabled { opacity: 0.35; cursor: default; }
  .btn-end-game.on { border-color: var(--accent); color: var(--accent); }
  .btn-end-game:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); transform: translateY(-1px); }
  .btn-end-game.danger:hover:not(:disabled) { border-color: var(--red); color: var(--red); }
  .btn-end-game.start { border-color: var(--green); color: var(--green); }
  .players-section { flex: 1 1 0; overflow: hidden; display: flex; flex-direction: column; padding: 1.2vw 1.6vw; min-height: 0; border-radius: 24px; background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); }
  /* The rows share the height of the card, up to a limit, and sit in the middle of it: a few players
     get big rows, many players fill it. */
  .list-fill { position: relative; flex: 1; min-height: 0; }
  /* Absolutely placed, so the list never makes the card taller: it fills what the player card and the
     board leave and scrolls when there are more players. */
  .tv-elim-list { list-style: none; position: absolute; inset: 0; overflow-y: auto; display: flex; flex-direction: column; justify-content: safe center; gap: 0.5vh; }
  .tv-elim-list li {
    flex: 1 0 auto; max-height: 3.2vw; min-height: 3.2vw;
    /* avatar | name | wins | lives: the wins of every row stand in one column */
    display: grid; grid-template-columns: auto minmax(0, 1fr) 3.2em auto; align-items: center; column-gap: 1.2vw;
    padding: 0 1.6vw; border-radius: 18px;
    font-size: clamp(0.85rem, 1.5vw, 1.9rem);
    transition: background 0.2s;
  }
  .row-avatar { display: block; width: 1.5em; height: 1.5em; flex-shrink: 0; }
  .row-wins { text-align: right; }
  .row-lives { font-size: 0.8em; }
  .row-wins :global(.win-count) { margin-left: 0; font-size: 0.7em; vertical-align: baseline; }
  .row-avatar :global(svg) { width: 100%; height: 100%; }
  .elim-current-row {
    color: var(--text);
    background: linear-gradient(90deg, color-mix(in srgb, var(--green) 14%, transparent), transparent);
    border: 1px solid color-mix(in srgb, var(--green) 25%, transparent);
  }
  .elim-current-row .name-crown-wrap { color: var(--green); font-weight: 700; }
  .name-crown-wrap { position: relative; display: inline-block; }
</style>
