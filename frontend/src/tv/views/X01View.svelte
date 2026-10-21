<script>
  import { confirmDialog } from '../../lib/confirm.js';
  import { navigate } from '../../lib/router.js';
  import { t } from '../../lib/i18n.js';
  // Ports #active X01 display of the former tv.html and migrates the
  // Scoreboard-tab controls of index.html here (Undo/Next Player/Next Leg/Reset Board,
  // throw-correction row, abandoned-match warning + force-clear) — the
  // Scoreboard tab itself goes away entirely per the decided
  // navigation redesign; the TV view is now the only place X01 controls live.
  import { cap, isBoardStopped } from '../../lib/util.js';
  import { getCheckout } from '../../lib/checkout.js';
  import { api } from '../../lib/api.js';
  import { health } from '../../lib/stores/health.js';
  import { abortTournament } from '../../lib/tournament.js';
  import Avatar from '../../lib/components/Avatar.svelte';
  import { gameState } from '../../lib/stores/gameState.js';
  import Icon from '../../lib/components/Icon.svelte';
  import DartBoard from '../../lib/components/DartBoard.svelte';
  import DartCorrectModal from './DartCorrectModal.svelte';

  const ABANDONED_MATCH_THRESHOLD_S = 900;

  // `own`: the snapshot of a match played in Breakfast. Its controls go to /api/x01/*, not to the
  // Autodarts match, and there is no next leg or board reset (the legs follow from the darts).
  let { game = {}, sessionStats = {}, hasCloudControl = false, boardDarts = [], own = null, tournament = null } = $props();
  let ownMatch = $derived(!!(own && own.active && own.phase === 'playing'));
  let canControl = $derived(ownMatch || hasCloudControl);
  let inTournament = $derived(!!(tournament && tournament.active && tournament.current));

  let cur = $derived(game.current || {});
  // The board stopped (camera standby): Start brings it back, until then there is nothing to reset.
  let boardStopped = $derived(isBoardStopped(game.board_status));
  let isX01 = $derived(game.game_mode && (game.game_mode.includes('01') || game.game_mode === 'Random Checkout'));
  let rem = $derived(parseInt(cur.remaining));
  let checkoutHint = $derived.by(() => {
    if (!isX01 || !(rem >= 2 && rem <= 170)) return '';
    const co = getCheckout(rem);
    return co ? '→ ' + co.join('  ') : '';
  });
  // In checkout range but no 3-dart combination exists at all (the classic
  // "bogey numbers": 169, 168, 166, ...) — distinct from simply not being
  // in checkout range yet, which just renders nothing.
  let isBogey = $derived(isX01 && rem >= 2 && rem <= 170 && !checkoutHint);

  let rows = $derived.by(() => {
    const players = game.players || {};
    const scores = game.remaining_scores || {};
    return Object.entries(players).map(([idx, p]) => ({
      idx: parseInt(idx),
      name: p.name,
      score: p.remaining ?? scores[`player${parseInt(idx) + 1}`] ?? '—',
      legs_won: p.legs_won ?? 0,
    })).sort((a, b) => a.idx - b.idx);
  });

  let selectedDartNum = $state(1);
  let boardOpen = $state(false);
  let canCorrect = $derived(canControl && game.match_started);

  function openCorrect(n) {
    if (!canCorrect) return;      // an empty box enters a dart the board did not see
    selectedDartNum = n;
    boardOpen = true;
  }

  const OWN_ACTIONS = { undo: 'undo', 'next-player': 'next' };
  async function ctrl(action) {
    await api('POST', ownMatch && OWN_ACTIONS[action] ? `/api/x01/${OWN_ACTIONS[action]}` : `/api/control/${action}`);
  }
  async function cancelMatch() {
    if (inTournament) {
      if (await abortTournament()) navigate('tournament');
      return;
    }
    if (!await confirmDialog(t('Cancel the current game?'))) return;
    await api('POST', '/api/x01/stop');
    navigate('home');
  }
  async function forceClearMatch() {
    if (!await confirmDialog(t('Clear the current match locally? Only do this if it looks stuck/abandoned — this does not touch the match on the Autodarts side.'))) return;
    await api('POST', '/api/control/force-clear-match');
  }

  function dartBoxClass(raw, pts, isBust) {
    return [raw != null && pts === 0 ? 'miss' : '', isBust ? 'bust' : ''].filter(Boolean).join(' ');
  }

  let correctEndpoint = $derived(ownMatch ? '/api/x01/correct-dart' : '/api/control/correct-throw');

  let showAbandonedWarning = $derived(
    !ownMatch && $health.matchActive && $health.secondsSinceActivity != null && $health.secondsSinceActivity > ABANDONED_MATCH_THRESHOLD_S
  );
  let abandonedText = $derived.by(() => {
    if (!showAbandonedWarning) return '';
    const mins = Math.round($health.secondsSinceActivity / 60);
    return t('Match open for {mins} min with no activity — looks abandoned on the Autodarts side.', { mins });
  });
</script>

<div class="x01-layout">
  <div class="x01-main">
    {#if showAbandonedWarning}
      <div class="abandoned-warning">
        <span>{abandonedText}</span>
        <button class="btn-ctrl danger" onclick={forceClearMatch}>{t('⚠ Force clear match')}</button>
      </div>
    {/if}

    <div class="player-card">
      <div class="name-row">
        <div class="who">
          <span class="swatch"><Avatar name={game.active_player_name || ''} color={$gameState.player_colors?.[game.active_player_name] || null} size={100} /></span>
          <div class="player-name">{cap(game.active_player_name || '—')}</div>
        </div>
        <div id="coHint">
          {#if checkoutHint}{checkoutHint}{:else if isBogey}<span class="bogey-badge">{t('Bogey — no checkout')}</span>{/if}
        </div>
        <div class="turn-total">
          <span class="tlabel">{t('Total')}</span>
          <span class="tval">{cur.turn_score ?? 0}</span>
          {#if cur.is_bust}<span class="bust-badge visible">{t('BUST')}</span>{/if}
        </div>
      </div>
      <div class="darts-row">
        {#each [1, 2, 3] as n}
          {@const raw = cur[`throw${n}_raw`]}
          {@const pts = cur[`throw${n}_points`]}
          {@const isBust = cur.is_bust && cur.last_dart_number >= n}
          <button type="button" class="dart-box {dartBoxClass(raw, pts, isBust)}" class:correctable={canCorrect}
                  onclick={() => openCorrect(n)}>
            <div class="dlabel">D{n}</div>
            <div class="dval">{raw != null ? String(raw).toUpperCase() : '—'}</div>
            <div class="dsub">{raw != null && pts != null ? `(${pts})` : ''}</div>
          </button>
        {/each}
        <div class="rest-col">{cur.remaining ?? '—'}</div>
      </div>
      <div class="control-bar">
        <button class="btn-ctrl" disabled={!canControl || !game.match_started} onclick={() => ctrl('undo')}>{t('↩ Undo')}</button>
        <button class="btn-ctrl" disabled={!canControl || !game.match_started} onclick={() => ctrl('next-player')}>{t('⏭ Next')}</button>
        {#if !ownMatch}
          <button class="btn-ctrl" disabled={!hasCloudControl || !game.match_started} onclick={() => ctrl('next-game')}>{t('▶▶ Next Leg')}</button>
        {/if}
        {#if boardStopped}
          <button class="btn-ctrl start" disabled={!hasCloudControl} onclick={() => ctrl('start-board')}><Icon name="board" size={20} />{t('Start')}</button>
        {:else}
          <button class="btn-ctrl danger" disabled={!hasCloudControl} onclick={() => ctrl('reset-board')}><Icon name="board" size={20} />{t('Reset')}</button>
        {/if}
      </div>
    </div>

    <div class="players-section">
      <div class="list-fill"><div class="list-scroll"><table>
        <thead>
          <tr><th>{t('Player')}</th><th class="num-cell">{t('Remaining')}</th><th class="num-cell">{t('Legs')}</th><th class="num-cell">{t('Avg')}</th></tr>
        </thead>
        <tbody>
          {#each rows as r (r.idx)}
            {@const ps = sessionStats[r.name] || {}}
            <tr class:current-row={r.idx === game.active_player_index}>
              <td>{cap(r.name || '—')}</td>
              <td class="num-cell">{r.score}</td>
              <td class="num-cell muted">{r.legs_won}</td>
              <td class="num-cell muted">{ps.avg3 != null ? ps.avg3.toFixed(1) : '—'}</td>
            </tr>
          {/each}
        </tbody>
      </table></div></div>
    </div>
  </div>
  <div class="x01-board">
    <DartBoard readonly darts={boardDarts} />
    {#if ownMatch}
      <button type="button" class="btn-cancel" onclick={cancelMatch}>{inTournament ? t('Abort tournament') : t('✕ Cancel')}</button>
    {/if}
  </div>
</div>

{#if boardOpen}
  <DartCorrectModal dartIndex={selectedDartNum - 1} endpoint={correctEndpoint} onClose={() => (boardOpen = false)} />
{/if}

<style>
  .player-card {
    flex: 0 0 21vw; display: flex; flex-direction: column; justify-content: space-between; gap: 1vw; padding: 2vw 2.2vw 1.5vw; border-radius: 24px;
    background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur);
  }
  .name-row { display: flex; align-items: center; justify-content: space-between; gap: 1.5vw; }
  .who { display: flex; align-items: center; gap: 1vw; min-width: 0; }
  .swatch { width: 1.5em; height: 1.5em; font-size: clamp(1.4rem, 3vw, 3rem); border-radius: 50%; flex-shrink: 0; overflow: visible; }
  .swatch :global(svg) { width: 100%; height: 100%; }
  .player-name { font-size: clamp(1.5rem, 3.5vw, 4rem); font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.1em; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  /* Fixed width for three digits, so the dart boxes do not move when the score gets shorter. */
  .rest-col {
    align-self: center;
    font-size: var(--rest-fs); font-weight: 900; color: var(--green); line-height: 1; text-align: right; font-variant-numeric: tabular-nums;
    text-shadow: 0 0 32px color-mix(in srgb, var(--green) 35%, transparent);
  }
  #coHint { flex: 1; text-align: right; font-size: clamp(1rem, 2.5vw, 2.5rem); font-weight: 700; color: var(--yellow); letter-spacing: 0.08em; white-space: nowrap; }
  .bogey-badge {
    display: inline-block; font-size: 0.5em; font-weight: 700; color: var(--red);
    background: color-mix(in srgb, var(--red) 15%, transparent);
    border: 1px solid var(--red); border-radius: 999px; padding: 0.2em 0.7em;
    letter-spacing: 0.04em; text-transform: uppercase;
  }
  .darts-row { display: grid; --rest-fs: clamp(3rem, 7vw, 8rem); grid-template-columns: 1fr 1fr 1fr calc(var(--rest-fs) * 2.1); gap: 1vw; align-items: stretch; min-height: 6.7vw; }
  .dart-box {
    background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow);
    border-radius: 16px; padding: 0.6vw 0.8vw; text-align: center;
    font-family: inherit; color: inherit; cursor: default;
    transition: border-color 0.15s, transform 0.15s, box-shadow 0.15s;
  }
  .dart-box.correctable { cursor: pointer; }
  .dart-box.correctable:hover {
    border-color: var(--accent);
    transform: translateY(-2px);
    box-shadow: 0 8px 20px -10px color-mix(in srgb, var(--accent) 50%, transparent);
  }
  .dart-box .dlabel { font-size: clamp(0.6rem, 0.9vw, 1rem); color: var(--muted); margin-bottom: 2px; }
  .dart-box .dval { font-size: clamp(1.2rem, 2.5vw, 3rem); font-weight: 800; }
  .dart-box .dsub { font-size: clamp(0.6rem, 0.9vw, 1rem); color: var(--muted); min-height: 1.2em; }
  .dart-box.miss .dval { color: var(--red); }
  .dart-box.bust { border-color: var(--red); box-shadow: 0 8px 20px -10px color-mix(in srgb, var(--red) 50%, transparent); }
  .turn-total { display: flex; align-items: baseline; justify-content: flex-end; gap: 0.5vw; white-space: nowrap; }
  .turn-total .tlabel { font-size: clamp(0.7rem, 1.1vw, 1.2rem); color: var(--muted); }
  .turn-total .tval {
    font-size: clamp(1.6rem, 3.4vw, 4rem); font-weight: 800; color: var(--yellow);
    text-shadow: 0 0 28px color-mix(in srgb, var(--yellow) 35%, transparent);
  }
  .bust-badge { background: var(--red); color: #fff; border-radius: 999px; padding: 0.1em 0.6em; font-size: clamp(0.7rem, 1.2vw, 1.3rem); font-weight: 700; }
  .players-section { flex: 1 1 0; overflow: hidden; padding: 1.2vw 1.6vw; display: flex; flex-direction: column; min-height: 0; border-radius: 24px; background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); }
  /* Absolutely placed, so the table never makes the card taller: it fills what the player card and the
     board leave and scrolls when there are more players. */
  .list-fill { position: relative; flex: 1; min-height: 0; }
  .list-scroll { position: absolute; inset: 0; overflow-y: auto; }
  .players-section table { width: 100%; border-collapse: collapse; }
  .players-section th { font-size: clamp(0.65rem, 1.1vw, 1.2rem); color: var(--muted); font-weight: 500; text-align: left; padding: 0.4vw 0.6vw; border-bottom: 1px solid var(--glass-border); }
  .players-section td { font-size: clamp(0.85rem, 1.5vw, 1.9rem); padding: 0.68vw 0.6vw; border-bottom: 1px solid var(--glass-border); transition: background 0.2s; }
  tr.current-row td { color: var(--text); background: color-mix(in srgb, var(--green) 10%, transparent); }
  tr.current-row td:first-child { color: var(--green); font-weight: 700; border-radius: 8px 0 0 8px; }
  tr.current-row td:last-child { border-radius: 0 8px 8px 0; }
  .num-cell, .players-section th.num-cell { text-align: right; }
  .muted { color: var(--muted); }
  .control-bar { display: flex; flex-wrap: wrap; gap: 1vw; }
  .btn-ctrl {
    flex: 1; min-width: 120px;
    background: var(--glass); border: 1px solid var(--glass-border); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2);
    color: var(--text); border-radius: 999px;
    padding: 0.75rem 0.5rem; font-size: clamp(1rem, 1.5vw, 1.6rem); font-weight: 600;
    cursor: pointer; text-align: center; display: inline-flex; align-items: center; justify-content: center; gap: 0.5em;
    transition: border-color 0.15s, color 0.15s, transform 0.15s;
  }
  .btn-ctrl:hover { border-color: var(--accent); color: var(--accent); transform: translateY(-1px); }
  .btn-ctrl:disabled { opacity: 0.35; cursor: default; transform: none; }
  .btn-ctrl.danger:hover { border-color: var(--red); color: var(--red); }
  .btn-ctrl.start { border-color: var(--green); color: var(--green); }
  .x01-layout { flex: 1; display: flex; gap: 1.5vw; padding: 1.3vw 2vw; min-height: 0; }
  .x01-main { flex: 3 1 0; min-width: 0; display: flex; flex-direction: column; gap: 1.2vw; min-height: 0; }
  .x01-board {
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
  .abandoned-warning {
    display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap;
    background: rgba(248, 113, 113, 0.1); border: 1px solid var(--red);
    border-radius: 16px; padding: 0.75rem 1rem; margin: 0;
    color: var(--red); font-size: 0.85rem;
  }
  .abandoned-warning .btn-ctrl { flex: none; min-width: 0; }

  /* On phone-width viewports, drop the lower-priority Avg
     column — Player/Remaining/Legs stay since those are what you'd
     actually glance at the TV view for on a phone. */
  @media (max-width: 480px) {
    .players-section th:nth-child(4), .players-section td:nth-child(4) {
      display: none;
    }
    .x01-layout { flex-direction: column; }
    .x01-layout { padding: 3vw; gap: 3vw; }
    .control-bar { flex-direction: column; }
    .btn-ctrl { min-width: 0; }
  }
</style>
