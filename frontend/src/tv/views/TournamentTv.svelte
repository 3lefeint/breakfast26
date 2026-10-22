<script>
  import { confirmDialog } from '../../lib/confirm.js';
  import { navigate } from '../../lib/router.js';
  import { t } from '../../lib/i18n.js';
  // The tournament on the TV between the matches: the whole bracket with the match that is next outlined,
  // and below it what happens now: a result that waits (the next match starts by itself, or at once; an
  // undo is still possible), the pairing that is next after a restart, or the winner of the tournament.
  import { shownName } from '../../lib/util.js';
  import { api } from '../../lib/api.js';
  import { nextMatch, abortTournament, closeTournament, roundName } from '../../lib/tournament.js';
  import TournamentBracket from '../../lib/components/TournamentBracket.svelte';
  import Crown from '../../lib/components/Crown.svelte';
  import ConfettiBurst from '../../lib/components/ConfettiBurst.svelte';

  let { snap } = $props();

  let pending = $derived(snap.pending);
  let next = $derived(snap.next);
  let rounds = $derived(snap.rounds?.length || 0);
  let isFinal = $derived(pending && pending.round === rounds - 1);
  let result = $derived.by(() => {
    if (!pending?.legs) return '';
    return Object.entries(pending.legs).map(([name, n]) => `${shownName(name)} ${n}`).join(' : ');
  });

  async function undo() {
    if (!await confirmDialog(t('Undo the last completed turn?'))) return;
    await api('POST', '/api/x01/undo');
  }

  async function abort() {
    if (await abortTournament()) navigate('tournament');
  }

  async function done() {
    await closeTournament();
    navigate('tournament');
  }
</script>

{#if snap.phase === 'finished'}<ConfettiBurst />{/if}

<div class="stage">
  <div class="top">
    {#if snap.phase === 'finished'}
      <div class="winner"><Crown />{t('{name} wins the tournament', { name: shownName(snap.winner || '') })}</div>
    {:else if pending}
      <div class="winner">{t('{name} wins', { name: shownName(pending.winner) })}<span class="result">{result}</span></div>
    {:else if next}
      <div class="winner small">{roundName(next.round, rounds)}: {shownName(next.a || '')} – {shownName(next.b || '')}</div>
    {/if}
  </div>

  <div class="bracket-area"><TournamentBracket {snap} /></div>

  <div class="bar">
    {#if pending}
      {#if pending.next_in != null}
        <span class="info">{t('Next match in {n} s', { n: pending.next_in })}</span>
        <button class="btn" onclick={nextMatch}>{t('Start now')}</button>
      {:else}
        <button class="btn" onclick={nextMatch}>{isFinal ? t('Finish the tournament') : t('Start now')}</button>
      {/if}
      <button class="btn ghost" onclick={undo}>{t('↩ Undo last turn')}</button>
    {:else if snap.phase === 'idle'}
      <button class="btn" onclick={nextMatch}>{t('Start next match')}</button>
    {/if}
    {#if snap.phase === 'finished'}
      <button class="btn" onclick={done}>{t('Done')}</button>
    {:else}
      <button class="btn ghost danger" onclick={abort}>{t('Abort tournament')}</button>
    {/if}
  </div>
</div>

<style>
  .stage { flex: 1; min-width: 0; min-height: 0; display: flex; flex-direction: column; gap: 1.4vw; }
  .top { min-height: 3.2rem; display: flex; align-items: center; justify-content: center; }
  .winner { font-size: clamp(1.6rem, 4vw, 3.6rem); font-weight: 800; color: var(--green); display: flex; align-items: baseline; gap: 1.2rem; flex-wrap: wrap; justify-content: center; position: relative; }
  .winner.small { font-size: clamp(1.1rem, 2.4vw, 2.2rem); color: var(--text); font-weight: 700; }
  .result { color: var(--muted); font-size: 0.55em; font-weight: 600; }
  .bracket-area { flex: 1; min-height: 0; overflow: auto; padding: 1vw 1.4vw; border-radius: 24px; background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); }
  .bar { display: flex; align-items: center; gap: 0.8rem; flex-wrap: wrap; justify-content: center; }
  .info { color: var(--muted); font-size: clamp(0.9rem, 1.5vw, 1.4rem); }
  .btn { background: #166534; color: #fff; border: none; border-radius: 999px; padding: 0.7rem 1.6rem; font-size: 1rem; font-weight: 600; cursor: pointer; }
  .btn.ghost { background: var(--glass); color: color-mix(in srgb, var(--text) 82%, transparent); border: 1px solid var(--glass-border); }
  .btn.ghost:hover { border-color: var(--accent); color: var(--text); }
  .btn.danger:hover { border-color: var(--red); color: var(--red); }
</style>
