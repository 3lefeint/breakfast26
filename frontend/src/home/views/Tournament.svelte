<script>
  import { t } from '../../lib/i18n.js';
  // Home's Tournament page: the setup and the tournaments played so far, or, while one is on, its bracket
  // with the controls. The matches themselves are played on /tv.
  import { onMount } from 'svelte';
  import { tournament } from '../../lib/stores/tournament.js';
  import { cap } from '../../lib/util.js';
  import { apiJson } from '../../lib/api.js';
  import { nextMatch, abortTournament, closeTournament } from '../../lib/tournament.js';
  import TournamentSetup from './TournamentSetup.svelte';
  import TournamentBracket from '../../lib/components/TournamentBracket.svelte';
  import PageHeader from '../../lib/components/PageHeader.svelte';

  let history = $state([]);
  async function loadHistory() {
    try { history = await apiJson('GET', '/api/tournament/history'); } catch (_) { history = []; }
  }
  onMount(loadHistory);
  $effect(() => { if (!$tournament?.active) loadHistory(); });

  let snap = $derived($tournament);
  const STATUS = { finished: () => t('Finished'), aborted: () => t('Aborted') };

  function dateOf(iso) {
    return iso ? new Date(iso).toLocaleDateString() : '';
  }
</script>

<PageHeader title={t('Tournament')}>
  {#snippet info()}
    <p>{t('A tournament is a knockout competition in X01: the players are drawn into a bracket, every match is played to a number of legs and the loser is out. The winner of the final wins the tournament. If the number of players does not fit the bracket, some players get a bye and go straight to the next round.')}</p>
    <p><strong>{t('Game settings:')}</strong></p>
    <ul>
      <li>{t('Base Score, In Mode, Out Mode, Max Rounds and Bull-Off work as in X01 and apply to every match.')}</li>
      <li><strong>{t('Legs per round')}:</strong> {t('Number of legs required to win a match in that round, e.g. more legs in the semi-finals and the final.')}</li>
      <li><strong>{t('Bracket')}:</strong> {t('The bracket is drawn at random as soon as two players are chosen. Click two seats to swap them, or draw again.')}</li>
    </ul>
    <p>{t('The next match starts by itself half a minute after a result; the final waits until you start it.')}</p>
  {/snippet}
</PageHeader>

{#if snap && snap.active}
  <div class="section">
    {#if snap.phase === 'finished'}
      <div class="heading">{t('{name} wins the tournament', { name: cap(snap.winner || '') })}</div>
    {/if}
    <TournamentBracket {snap} />
    <div class="actions">
      <a class="btn btn-start" href="/tv">{t('Open TV')}</a>
      {#if snap.phase === 'idle'}
        <button class="btn ghost" onclick={nextMatch}>{t('Start next match')}</button>
      {/if}
      {#if snap.phase === 'finished'}
        <button class="btn ghost" onclick={closeTournament}>{t('Done')}</button>
      {:else}
        <button class="btn ghost" onclick={abortTournament}>{t('Abort tournament')}</button>
      {/if}
    </div>
  </div>
{:else}
  <TournamentSetup />

  <div class="section">
    <div class="section-title">{t('Tournaments played')}</div>
    {#if history.length === 0}
      <p class="muted">{t('No tournaments yet.')}</p>
    {:else}
      <ul class="history">
        {#each history as h (h.id)}
          <li>
            <span class="when">{dateOf(h.created_at)}</span>
            <span class="who">{h.winner ? t('{name} wins', { name: cap(h.winner) }) : (STATUS[h.status] ? STATUS[h.status]() : h.status)}</span>
            <span class="meta">{h.players.length} {t('players')} · {h.config.start}</span>
            <span class="status" class:aborted={h.status === 'aborted'}>{STATUS[h.status] ? STATUS[h.status]() : ''}</span>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
{/if}

<style>
  .section { background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); border-radius: 16px; padding: 1.25rem; margin-bottom: 1rem; }
  .section-title { font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 1rem; }
  .heading { font-size: 1.6rem; font-weight: 800; color: var(--green); margin-bottom: 1rem; }
  .muted { color: var(--muted); margin: 0; }
  .actions { display: flex; gap: 0.6rem; flex-wrap: wrap; margin-top: 1rem; }
  .btn { border: none; border-radius: 8px; padding: 0.65rem 1.5rem; font-size: 0.95rem; font-weight: 600; cursor: pointer; text-decoration: none; display: inline-block; }
  .btn-start { background: #166534; color: #fff; }
  .btn.ghost { background: var(--glass); color: color-mix(in srgb, var(--text) 82%, transparent); border: 1px solid var(--glass-border); }
  .btn.ghost:hover { border-color: var(--accent); color: var(--text); }
  .history { list-style: none; margin: 0; padding: 0; }
  .history li { display: grid; grid-template-columns: 6rem 1fr auto auto; gap: 1rem; padding: 0.5rem 0; border-bottom: 1px solid var(--glass-border); align-items: center; }
  .history li:last-child { border: none; }
  .when, .meta { color: var(--muted); font-size: 0.85rem; }
  .status { font-size: 0.75rem; color: var(--muted); }
  .status.aborted { color: var(--red); }
</style>
