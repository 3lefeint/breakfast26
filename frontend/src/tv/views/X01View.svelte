<script>
  // Ports tv.html's #active X01 display and migrates index.html's
  // Scoreboard-tab controls here (Undo/Next Player/Next Leg/Reset Board,
  // throw-correction row, abandoned-match warning + force-clear) — the
  // Scoreboard tab itself goes away entirely per the decided
  // navigation redesign; /tv is now the only place X01 controls live.
  import { cap } from '../../lib/util.js';
  import { getCheckout } from '../../lib/checkout.js';
  import { api } from '../../lib/api.js';
  import { health } from '../../lib/stores/health.js';
  import DartBoard from '../../lib/components/DartBoard.svelte';
  import DartCorrectModal from './DartCorrectModal.svelte';

  const ABANDONED_MATCH_THRESHOLD_S = 900;

  let { game = {}, sessionStats = {}, hasCloudControl = false, boardDarts = null } = $props();

  let cur = $derived(game.current || {});
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

  let legLabel = $derived(game.current_leg > 1 ? `Leg ${game.current_leg}` : null);
  let matchMeta = $derived([game.game_mode, game.points_start ? `${game.points_start} pts` : null, game.special, legLabel].filter(Boolean).join(' · '));

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
  let correctField = $state('');
  let boardOpen = $state(false);
  let canCorrect = $derived(hasCloudControl && game.match_started);

  function openCorrect(n) {
    if (!canCorrect || cur[`throw${n}_raw`] == null) return;
    selectedDartNum = n;
    boardOpen = true;
  }

  async function ctrl(action) {
    await api('POST', `/api/control/${action}`);
  }
  async function correctThrowSubmit() {
    const field = correctField.trim();
    if (!field) return;
    await api('POST', '/api/control/correct-throw', { dart: selectedDartNum, field: field.toUpperCase() });
    correctField = '';
  }
  async function forceClearMatch() {
    if (!confirm('Clear the current match locally? Only do this if it looks stuck/abandoned — this does not touch the match on the Autodarts side.')) return;
    await api('POST', '/api/control/force-clear-match');
  }

  function dartBoxClass(pts, isBust) {
    return [pts === 0 ? 'miss' : '', isBust ? 'bust' : ''].filter(Boolean).join(' ');
  }

  let showAbandonedWarning = $derived(
    $health.matchActive && $health.secondsSinceActivity != null && $health.secondsSinceActivity > ABANDONED_MATCH_THRESHOLD_S
  );
  let abandonedText = $derived.by(() => {
    if (!showAbandonedWarning) return '';
    const mins = Math.round($health.secondsSinceActivity / 60);
    return `Match open for ${mins} min with no activity — looks abandoned on the Autodarts side.`;
  });
</script>

<div class="x01-layout">
  <div class="x01-main">
    {#if showAbandonedWarning}
      <div class="abandoned-warning">
        <span>{abandonedText}</span>
        <button class="btn-ctrl danger" onclick={forceClearMatch}>⚠ Force clear match</button>
      </div>
    {/if}

    <div class="match-info">{matchMeta || 'No active match'}</div>

    <div class="player-card">
      <div class="player-name">{cap(game.active_player_name || '—')}</div>
      <div class="player-score">{cur.remaining ?? '—'}</div>
      <div id="coHint">
        {#if checkoutHint}{checkoutHint}{:else if isBogey}<span class="bogey-badge">Bogey — no checkout</span>{/if}
      </div>
      <div class="darts-row">
        {#each [1, 2, 3] as n}
          {@const raw = cur[`throw${n}_raw`]}
          {@const pts = cur[`throw${n}_points`]}
          {@const isBust = cur.is_bust && cur.last_dart_number >= n}
          <button type="button" class="dart-box {dartBoxClass(pts, isBust)}" class:correctable={canCorrect && raw != null}
                  onclick={() => openCorrect(n)}>
            <div class="dlabel">D{n}</div>
            <div class="dval">{raw != null ? String(raw).toUpperCase() : '—'}</div>
            <div class="dsub">{raw != null && pts != null ? `(${pts})` : ''}</div>
          </button>
        {/each}
        <div class="turn-total">
          <div class="tlabel">Total</div>
          <div class="tval">{cur.turn_score ?? 0}</div>
          <div>{#if cur.is_bust}<span class="bust-badge visible">BUST</span>{/if}</div>
        </div>
      </div>
    </div>

    <div class="players-section">
      <table>
        <thead>
          <tr><th>Player</th><th class="num-cell">Remaining</th><th class="num-cell">Legs</th><th class="num-cell">Avg</th><th class="num-cell">CO%</th></tr>
        </thead>
        <tbody>
          {#each rows as r (r.idx)}
            {@const ps = sessionStats[r.name] || {}}
            <tr class:current-row={r.idx === game.active_player_index}>
              <td>{cap(r.name || '—')}</td>
              <td class="num-cell">{r.score}</td>
              <td class="num-cell muted">{r.legs_won}</td>
              <td class="num-cell muted">{ps.avg3 != null ? ps.avg3.toFixed(1) : '—'}</td>
              <td class="num-cell muted">{ps.co_attempts ? ps.co_pct + '%' : '—'}</td>
            </tr>
          {/each}
        </tbody>
      </table>

      <div class="section-title">Control</div>
      <div class="control-bar">
        <button class="btn-ctrl" disabled={!hasCloudControl || !game.match_started} onclick={() => ctrl('undo')}>↩ Undo</button>
        <button class="btn-ctrl" disabled={!hasCloudControl || !game.match_started} onclick={() => ctrl('next-player')}>⏭ Next Player</button>
        <button class="btn-ctrl" disabled={!hasCloudControl || !game.match_started} onclick={() => ctrl('next-game')}>▶▶ Next Leg</button>
        <button class="btn-ctrl danger" disabled={!hasCloudControl} onclick={() => ctrl('reset-board')}>⟳ Reset Board</button>
      </div>
      <div class="throw-correct-row">
        <span class="lbl">Correct:</span>
        <div class="dart-num-group">
          {#each [1, 2, 3] as n}
            <button class="btn-dart-num" class:sel={selectedDartNum === n} disabled={!hasCloudControl || !game.match_started} onclick={() => (selectedDartNum = n)}>D{n}</button>
          {/each}
        </div>
        <input class="field-input" placeholder="T20" maxlength="4" disabled={!hasCloudControl || !game.match_started}
               bind:value={correctField}
               oninput={(e) => { correctField = e.target.value.toUpperCase(); }}
               onkeydown={(e) => e.key === 'Enter' && correctThrowSubmit()}>
        <button class="btn-correct" disabled={!hasCloudControl || !game.match_started} onclick={correctThrowSubmit}>✓ Apply</button>
        <button class="btn-correct" disabled={!hasCloudControl || !game.match_started} onclick={() => (boardOpen = true)}>🎯 Board</button>
      </div>
    </div>
  </div>
  {#if boardDarts}
    <div class="x01-board"><DartBoard readonly darts={boardDarts} /></div>
  {/if}
</div>

{#if boardOpen}
  <DartCorrectModal dartIndex={selectedDartNum - 1} endpoint="/api/control/correct-throw" onClose={() => (boardOpen = false)} />
{/if}

<style>
  .match-info { font-size: 0.9rem; color: color-mix(in srgb, var(--text) 72%, transparent); margin: 0 0.5vw; }
  .player-card {
    flex: 0 0 auto; padding: 1.5vw 2.4vw; border-radius: 24px;
    background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur);
  }
  .player-name { font-size: clamp(1.5rem, 3.5vw, 4rem); font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 0.2em; }
  .player-score {
    font-size: clamp(4rem, 13vw, 14rem); font-weight: 900; color: var(--green); line-height: 0.9; margin-bottom: 0.15em;
    text-shadow: 0 0 36px color-mix(in srgb, var(--green) 35%, transparent);
  }
  #coHint { font-size: clamp(1rem, 2.5vw, 2.5rem); font-weight: 700; color: var(--yellow); letter-spacing: 0.08em; min-height: 1.3em; margin-bottom: 0.5em; }
  .bogey-badge {
    display: inline-block; font-size: 0.5em; font-weight: 700; color: var(--red);
    background: color-mix(in srgb, var(--red) 15%, transparent);
    border: 1px solid var(--red); border-radius: 999px; padding: 0.2em 0.7em;
    letter-spacing: 0.04em; text-transform: uppercase;
  }
  .darts-row { display: grid; grid-template-columns: 1fr 1fr 1fr auto; gap: 1vw; align-items: center; }
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
  .dart-box .dsub { font-size: clamp(0.6rem, 0.9vw, 1rem); color: var(--muted); }
  .dart-box.miss .dval { color: var(--red); }
  .dart-box.bust { border-color: var(--red); box-shadow: 0 8px 20px -10px color-mix(in srgb, var(--red) 50%, transparent); }
  .turn-total { text-align: right; padding-right: 0.5vw; }
  .turn-total .tlabel { font-size: clamp(0.6rem, 0.9vw, 1rem); color: var(--muted); }
  .turn-total .tval {
    font-size: clamp(1.5rem, 3.5vw, 4rem); font-weight: 800; color: var(--yellow);
    text-shadow: 0 0 28px color-mix(in srgb, var(--yellow) 35%, transparent);
  }
  .bust-badge { background: var(--red); color: #fff; border-radius: 999px; padding: 0.1em 0.6em; font-size: clamp(0.7rem, 1.2vw, 1.3rem); font-weight: 700; }
  .players-section { flex: 1; overflow-y: auto; overflow-x: hidden; padding: 1.2vw 2.4vw 1.5vw; display: flex; flex-direction: column; min-height: 0; border-radius: 24px; background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); }
  .players-section table { width: 100%; border-collapse: collapse; }
  .players-section th { font-size: clamp(0.65rem, 1.1vw, 1.2rem); color: var(--muted); font-weight: 500; text-align: left; padding: 0.4vw 0.6vw; border-bottom: 1px solid var(--glass-border); }
  .players-section td { font-size: clamp(0.85rem, 1.6vw, 2rem); padding: 0.5vw 0.6vw; border-bottom: 1px solid var(--glass-border); transition: background 0.2s; }
  tr.current-row td { color: var(--text); background: color-mix(in srgb, var(--green) 10%, transparent); }
  tr.current-row td:first-child { color: var(--green); font-weight: 700; border-radius: 8px 0 0 8px; }
  tr.current-row td:last-child { border-radius: 0 8px 8px 0; }
  .num-cell, .players-section th.num-cell { text-align: right; }
  .muted { color: var(--muted); }
  .section-title { font-size: 0.8rem; color: var(--muted); margin: 1rem 0 0.5rem; letter-spacing: 0.06em; text-transform: uppercase; }
  .control-bar { display: flex; flex-wrap: wrap; gap: 0.5rem; }
  .btn-ctrl {
    flex: 1; min-width: 120px;
    background: var(--glass); border: 1px solid var(--glass-border); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2);
    color: var(--text); border-radius: 999px;
    padding: 0.6rem 0.5rem; font-size: 0.85rem; font-weight: 600;
    cursor: pointer; text-align: center; transition: border-color 0.15s, color 0.15s, transform 0.15s;
  }
  .btn-ctrl:hover { border-color: var(--accent); color: var(--accent); transform: translateY(-1px); }
  .btn-ctrl:disabled { opacity: 0.35; cursor: default; transform: none; }
  .btn-ctrl.danger:hover { border-color: var(--red); color: var(--red); }
  .throw-correct-row { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; margin-top: 0.5rem; }
  .throw-correct-row .lbl { font-size: 0.8rem; color: var(--muted); white-space: nowrap; }
  .dart-num-group { display: flex; gap: 0.25rem; }
  .btn-dart-num { background: var(--glass); border: 1px solid var(--glass-border); color: var(--muted); border-radius: 999px; padding: 0.3rem 0.6rem; font-size: 0.8rem; cursor: pointer; transition: border-color 0.15s, color 0.15s; }
  .btn-dart-num.sel { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
  .btn-dart-num:disabled { opacity: 0.35; cursor: default; }
  .field-input { background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); color: var(--text); border-radius: 8px; padding: 0.3rem 0.6rem; font-size: 0.9rem; width: 70px; text-transform: uppercase; }
  .field-input:focus { outline: none; border-color: var(--accent); }
  .field-input:disabled { opacity: 0.35; }
  .btn-correct { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 999px; padding: 0.3rem 0.85rem; font-size: 0.85rem; font-weight: 600; cursor: pointer; white-space: nowrap; transition: border-color 0.15s, color 0.15s; }
  .btn-correct:hover { border-color: var(--accent); color: var(--accent); }
  .btn-correct:disabled { opacity: 0.35; cursor: default; }
  .x01-layout { flex: 1; display: flex; gap: 1.5vw; padding: 1.3vw 2vw; min-height: 0; }
  .x01-main { flex: 3 1 0; min-width: 0; display: flex; flex-direction: column; gap: 1.2vw; min-height: 0; }
  .x01-board {
    flex: 2 1 0; min-width: 0; display: flex; align-items: center; justify-content: center;
    padding: 1.5vw; border-radius: 24px; background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); --board-max: min(100%, 78vh);
  }
  .abandoned-warning {
    display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap;
    background: rgba(248, 113, 113, 0.1); border: 1px solid var(--red);
    border-radius: 16px; padding: 0.75rem 1rem; margin: 0;
    color: var(--red); font-size: 0.85rem;
  }
  .abandoned-warning .btn-ctrl { flex: none; min-width: 0; }

  /* On phone-width viewports, drop the lower-priority Avg/CO%
     columns — Player/Remaining/Legs stay since those are what you'd
     actually glance at /tv for on a phone. */
  @media (max-width: 480px) {
    .players-section th:nth-child(4), .players-section td:nth-child(4),
    .players-section th:nth-child(5), .players-section td:nth-child(5) {
      display: none;
    }
    .x01-layout { flex-direction: column; }
    .x01-layout { padding: 3vw; gap: 3vw; }
    .control-bar { flex-direction: column; }
    .btn-ctrl { min-width: 0; }
  }
</style>
