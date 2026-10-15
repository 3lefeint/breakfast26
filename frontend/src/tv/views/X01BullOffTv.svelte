<script>
  import { t } from '../../lib/i18n.js';
  // The bull-off before an X01 match: everybody throws one dart at the bull, the closest throws first,
  // the others follow by distance, players tied throw again. One dart counts as it lands and stays
  // shown (tap it to correct it, or to enter one the board did not see); the next player is up when the
  // darts are pulled, or with Next. When the order is set the match starts.
  import { flip } from 'svelte/animate';
  import { cap } from '../../lib/util.js';
  import { api } from '../../lib/api.js';
  import { dartLabel } from '../../lib/killer.js';
  import { ruleChips } from '../../lib/x01.js';
  import { abortTournament, roundName } from '../../lib/tournament.js';
  import DartBoard from '../../lib/components/DartBoard.svelte';
  import DartCorrectModal from './DartCorrectModal.svelte';

  let { x, tournament = null } = $props();
  let inTournament = $derived(!!(tournament && tournament.active && tournament.current));

  let starting = $derived(x.phase !== 'bull_off');
  let lastThrow = $derived(x.last_turn?.darts?.[0] || null);
  // The dart is on the board until it is pulled: then it is shown, and nothing after that.
  let markers = $derived(x.pull_darts && lastThrow ? [{ n: 1, x: lastThrow.x, y: lastThrow.y }] : []);
  let correcting = $state(false);

  async function stop() {
    if (inTournament) {
      if (await abortTournament()) window.location.href = '/#tournament';
      return;
    }
    if (!confirm(t('Cancel the current game?'))) return;
    await api('POST', '/api/x01/stop');
    window.location.href = '/';
  }

  // Goes on without pulling the darts, like the Next button of the games.
  async function next() {
    await api('POST', '/api/x01/next');
  }

  async function undo() {
    if (!confirm(t('Undo the last completed turn?'))) return;
    await api('POST', '/api/x01/undo');
  }
</script>

<div class="stage">
  <div class="bar">
    <div class="turn">
      <span class="turn-name">{starting ? t('Match starts …') : cap(x.current_player || '—')}</span>
      {#if !starting}<span class="turn-hint">{x.pull_darts ? t('Pull the darts') : t('Bull-off: one dart at the bull')}</span>{/if}
    </div>
    <div class="rules">
      {#if inTournament}<span class="rule-chip">{roundName(tournament.current.round, tournament.rounds.length)}</span>{/if}
      <span class="rule-chip">{x.rules.start}</span>
      {#each ruleChips(x) as chip}<span class="rule-chip">{chip}</span>{/each}
    </div>
  </div>

  <div class="body">
    <div class="board-col">
      <DartBoard readonly darts={markers} />
    </div>

    <div class="side">
      <ul class="k-list">
        {#each x.players as p, i (p.name)}
          <li class:current-row={p.current && !starting} animate:flip={{ duration: 300 }}>
            <span class="place">{p.placed ? i + 1 : ''}</span>
            <span class="name">{cap(p.name)}</span>
            <span class="num">{p.bull_off_mm != null ? `${p.bull_off_mm} mm` : ''}</span>
          </li>
        {/each}
      </ul>

      <div class="darts-row">
        <button type="button" class="dart-box" disabled={starting} onclick={() => (correcting = true)}>
          <span class="dlabel">{x.pull_darts ? `${t('Last throw')} · ${cap(x.last_turn?.player || '')}` : t('Enter a dart')}</span>
          <span class="dval">{x.pull_darts && lastThrow ? dartLabel(lastThrow) : '—'}</span>
        </button>
      </div>

      <div class="endgame-row">
        <button class="btn-end-game" onclick={undo}>{t('↩ Undo')}</button>
        {#if x.pull_darts}<button class="btn-end-game" onclick={next}>{t('⏭ Next')}</button>{/if}
        <button class="btn-end-game" onclick={stop}>{inTournament ? t('Abort tournament') : t('✕ Cancel')}</button>
      </div>
    </div>
  </div>
</div>

{#if correcting}
  <DartCorrectModal dartIndex={0} onClose={() => (correcting = false)} endpoint="/api/x01/correct-dart" />
{/if}

<style>
  .stage { flex: 1; min-width: 0; min-height: 0; display: flex; flex-direction: column; }
  .bar { display: flex; align-items: center; justify-content: space-between; gap: 2vw; padding: 0 1vw 0.8vw; flex-wrap: wrap; }
  .turn { display: flex; align-items: baseline; gap: 1vw; flex-wrap: wrap; min-width: 0; }
  .turn-name { font-size: clamp(1.6rem, 3.6vw, 3.6rem); font-weight: 900; text-transform: uppercase; letter-spacing: 0.06em; }
  .turn-hint { font-size: clamp(0.9rem, 1.6vw, 1.6rem); color: var(--muted); font-weight: 600; }
  .rules { display: flex; flex-wrap: wrap; gap: 0.4rem; }
  .rule-chip { font-size: clamp(0.65rem, 1vw, 1rem); color: var(--muted); border: 1px solid var(--glass-border); border-radius: 999px; padding: 0.1em 0.7em; }

  .body { flex: 1; min-height: 0; display: flex; gap: 2vw; padding: 0; }
  .board-col {
    flex: 1; min-width: 0; display: flex; align-items: center; justify-content: center;
    padding: 1vw; border-radius: 24px; background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); --board-max: min(calc(100vh - 250px), 56vw);
  }
  .side { flex: 0 0 clamp(340px, 36vw, 640px); min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 1.2vw; padding: 1.4vw; border-radius: 24px; background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); }

  .k-list { list-style: none; padding: 0; margin: 0; }
  .k-list li {
    display: grid; grid-template-columns: 2em 1fr 5.5em; align-items: center; gap: 1vw;
    padding: 0.5vw 1vw; margin-top: 0.5vw; border-radius: 10px;
    font-size: clamp(0.9rem, 1.6vw, 1.9rem); border: 1px solid transparent; transition: background 0.2s;
  }
  .k-list li:first-child { margin-top: 0; }
  .current-row {
    background: linear-gradient(90deg, color-mix(in srgb, var(--green) 14%, transparent), transparent);
    border-color: color-mix(in srgb, var(--green) 25%, transparent) !important;
  }
  .current-row .name { color: var(--green); font-weight: 700; }
  .place { color: var(--muted); font-weight: 700; text-align: center; }
  .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .num { font-weight: 900; color: var(--muted); text-align: right; }

  .darts-row { display: grid; grid-template-columns: 1fr; gap: 0.8vw; }
  .dart-box {
    display: flex; flex-direction: column; align-items: center;
    background: var(--glass); border: 1px solid var(--glass-border); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2); border-radius: 12px;
    padding: 0.5vw 0.8vw; font-family: inherit; color: inherit; cursor: pointer;
    transition: border-color 0.15s, transform 0.15s;
  }
  .dart-box:disabled { cursor: default; color: var(--muted); }
  .dart-box:not(:disabled):hover { border-color: var(--accent); transform: translateY(-2px); }
  .dlabel { font-size: clamp(0.6rem, 0.9vw, 1rem); color: var(--muted); }
  .dval { font-size: clamp(1.1rem, 2.2vw, 2.6rem); font-weight: 800; }

  .endgame-row { display: flex; gap: 0.6rem; margin-top: auto; }
  .btn-end-game {
    background: var(--glass); border: 1px solid var(--glass-border); color: color-mix(in srgb, var(--text) 80%, transparent); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2);
    border-radius: 999px; padding: 0.55rem 1.25rem;
    font-size: clamp(0.8rem, 1.3vw, 1rem); font-weight: 600; cursor: pointer;
    transition: border-color 0.15s, color 0.15s, background 0.15s;
  }
  .btn-end-game:hover { border-color: var(--red); color: var(--red); background: rgba(248, 113, 113, 0.08); }
</style>
