<script>
  // Elimination half of the Stats tab: headline numbers, how each player
  // finishes compared with chance, recent Elimination matches and per-player
  // activity.
  import { onMount } from 'svelte';
  import { cap } from '../../../lib/util.js';
  import Dashboard from '../Dashboard.svelte';
  import RecentMatches from './RecentMatches.svelte';
  import PlacementRows from './PlacementRows.svelte';
  import FormStrip from './FormStrip.svelte';
  import HeadToHead from './HeadToHead.svelte';
  import GameLengths from './GameLengths.svelte';

  let summary = $state(null);
  let players = $state([]);
  let headToHead = $state([]);
  let gameLengths = $state([]);
  let records = $state(null);
  let loadFailed = $state(false);

  onMount(async () => {
    try {
      const data = await fetch('/api/stats/elimination/overview').then((r) => r.json());
      summary = data.summary;
      players = data.players;
      headToHead = data.head_to_head;
      gameLengths = data.game_lengths;
      records = data.records;
    } catch (e) {
      loadFailed = true;
    }
  });

  function recordSub(r, showTarget) {
    if (!r) return '';
    const date = new Date(r.date).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
    return `${showTarget ? `had to beat ${r.target} · ` : ''}${cap(r.player)} · ${date}`;
  }

  function duration(minutes) {
    if (minutes == null) return '—';
    return minutes < 60 ? `${minutes.toFixed(1)} min` : `${(minutes / 60).toFixed(1)} h`;
  }
</script>

{#if loadFailed}
  <div class="empty">Could not load stats.</div>
{:else if summary}
  <div class="section-title">Overview</div>
  <div class="stat-tiles">
    <div class="stat-tile"><div class="stat-tile-label">Games</div><div class="stat-tile-value">{summary.games}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">Total playtime</div><div class="stat-tile-value">{duration(summary.total_minutes)}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">Average game</div><div class="stat-tile-value">{duration(summary.avg_minutes)}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">Longest game</div><div class="stat-tile-value">{duration(summary.longest_minutes)}</div></div>
  </div>
  {#if records}
    <div class="records">
      <div class="record">
        <div class="stat-tile-label">Highest score</div>
        <div class="stat-tile-value">{records.highest_score?.score ?? '—'}</div>
        <div class="record-sub">{recordSub(records.highest_score, false)}</div>
      </div>
      <div class="record">
        <div class="stat-tile-label">Highest score that still lost a life</div>
        <div class="stat-tile-value">{records.highest_lost_score?.score ?? '—'}</div>
        <div class="record-sub">{recordSub(records.highest_lost_score, true)}</div>
      </div>
    </div>
  {/if}

  <div class="section-title top">Wins and placements</div>
  <PlacementRows {players} />

  <div class="section-title top">Form · last 15 games</div>
  <FormStrip {players} />

  <div class="section-title top">Head to head</div>
  <HeadToHead pairs={headToHead} order={players.map((p) => p.player)} />

  <div class="section-title top">Game length · by lives</div>
  <GameLengths games={gameLengths} />
{/if}

<RecentMatches mode="elimination" />

<div class="section-title top2">Activity</div>
<Dashboard players={players.map((p) => p.player)} />

<style>
  .section-title { font-size: 0.8rem; color: var(--muted); margin: 0 0 0.6rem; letter-spacing: 0.06em; text-transform: uppercase; }
  .section-title.top { margin-top: 1.75rem; }
  .section-title.top2 { margin-top: 2rem; }
  .empty { color: var(--muted); text-align: center; padding: 1.5rem 0; }
  .stat-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 0.75rem; }
  .stat-tile {
    background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
    padding: 0.75rem 0.9rem; text-align: center;
  }
  .records { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; margin-top: 0.75rem; }
  .record {
    background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
    padding: 0.75rem 0.9rem; text-align: center;
  }
  .record-sub { font-size: 0.75rem; color: var(--muted); margin-top: 0.2rem; }
  @media (max-width: 600px) { .records { grid-template-columns: 1fr; } }
  .stat-tile-label { font-size: 0.7rem; color: var(--muted); margin-bottom: 0.3rem; }
  .stat-tile-value { font-size: 1.4rem; font-weight: 600; }
</style>
