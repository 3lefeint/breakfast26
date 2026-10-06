<script>
  import { t } from '../../../lib/i18n.js';
  // Killer half of the Stats tab: the overview with the records, who wins and how it compares to
  // chance, the form of the last games, head to head, and what each player did.
  import { onMount } from 'svelte';
  import { cap } from '../../../lib/util.js';
  import RecentMatches from './RecentMatches.svelte';
  import Panel from '../../../lib/components/Panel.svelte';
  import PlacementRows from './PlacementRows.svelte';
  import FormStrip from './FormStrip.svelte';
  import HeadToHead from './HeadToHead.svelte';
  import KillerPlayers from './KillerPlayers.svelte';

  let data = $state(null);
  let loadFailed = $state(false);

  onMount(async () => {
    try {
      data = await fetch('/api/stats/killer/overview').then((r) => r.json());
    } catch (e) {
      loadFailed = true;
    }
  });

  let summary = $derived(data?.summary || {});
  let records = $derived(data?.records || {});
  let competitors = $derived((data?.players || []).filter((p) => p.games > 0));

  function duration(minutes) {
    if (minutes == null) return '—';
    return minutes < 60 ? `${minutes.toFixed(1)} ${t('min')}` : `${(minutes / 60).toFixed(1)} h`;
  }
  function dateOf(d) { return new Date(d).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }); }
</script>

{#if loadFailed}
  <div class="empty">{t('Could not load stats.')}</div>
{:else if data}
  <div class="section-title">{t('Overview')}</div>
  <div class="stat-tiles">
    <div class="stat-tile"><div class="stat-tile-label">{t('Games')}</div><div class="stat-tile-value">{summary.games ?? 0}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">{t('Players per game')}</div><div class="stat-tile-value">{summary.avg_players ?? '—'}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">{t('Total playtime')}</div><div class="stat-tile-value">{duration(summary.total_minutes)}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">{t('Average game')}</div><div class="stat-tile-value">{duration(summary.avg_minutes)}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">{t('Longest game')}</div><div class="stat-tile-value">{duration(summary.longest_minutes)}</div></div>
  </div>
  <div class="records">
    <div class="record">
      <div class="stat-tile-label">{t('Most lives taken in a game')}</div>
      <div class="stat-tile-value">{records.most_lives_taken?.count ?? '—'}</div>
      <div class="record-sub">{#if records.most_lives_taken}{cap(records.most_lives_taken.player)} · {dateOf(records.most_lives_taken.date)}{/if}</div>
    </div>
    <div class="record">
      <div class="stat-tile-label">{t('Most knockouts in a game')}</div>
      <div class="stat-tile-value">{records.most_knockouts?.count ?? '—'}</div>
      <div class="record-sub">{#if records.most_knockouts}{cap(records.most_knockouts.player)} · {dateOf(records.most_knockouts.date)}{/if}</div>
    </div>
    <div class="record">
      <div class="stat-tile-label">{t('Fastest killer')}</div>
      <div class="stat-tile-value">{records.fastest_killer ? `${records.fastest_killer.turns} ${records.fastest_killer.turns === 1 ? t('turn') : t('turns')}` : '—'}</div>
      <div class="record-sub">{#if records.fastest_killer}{cap(records.fastest_killer.player)}{/if}</div>
    </div>
  </div>

  <div class="section-title top">{t('Wins and placements')}</div>
  <Panel><PlacementRows players={competitors} emptyText={t('No Killer games yet.')} /></Panel>

  <div class="section-title top">{t('Form · last 15 games')}</div>
  <Panel><FormStrip players={competitors} /></Panel>

  <div class="section-title top">{t('Head to head')}</div>
  <Panel><HeadToHead pairs={data.head_to_head} order={competitors.map((p) => p.player)} /></Panel>

  <div class="section-title top">{t('Players')}</div>
  <Panel><KillerPlayers players={data.players} /></Panel>
{/if}

<RecentMatches mode="killer" />

<style>
  .section-title { font-size: 0.8rem; color: var(--muted); margin: 0 0 0.6rem; letter-spacing: 0.06em; text-transform: uppercase; }
  .section-title.top { margin-top: 1.75rem; }
  .empty { color: var(--muted); text-align: center; padding: 1.5rem 0; }
  .stat-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 0.75rem; }
  .stat-tile { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 12px; box-shadow: var(--glass-shadow); padding: 0.75rem 0.9rem; text-align: center; }
  .records { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.75rem; margin-top: 0.75rem; }
  .record { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 12px; box-shadow: var(--glass-shadow); padding: 0.75rem 0.9rem; text-align: center; }
  .record-sub { font-size: 0.75rem; color: var(--muted); margin-top: 0.2rem; min-height: 1.1em; }
  @media (max-width: 600px) { .records { grid-template-columns: 1fr; } }
  .stat-tile-label { font-size: 0.7rem; color: var(--muted); margin-bottom: 0.3rem; }
  .stat-tile-value { font-size: 1.4rem; font-weight: 600; }
</style>
