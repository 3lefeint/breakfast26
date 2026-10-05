<script>
  // The per-player section of the Elimination view: player selector, activity
  // tiles, records and the activity charts, one bundled fetch per player via
  // /api/stats/dashboard/{name}.
  import { cap } from '../../lib/util.js';
  import ActivityBars from './stats/ActivityBars.svelte';
  import PositionHeatmap from './stats/PositionHeatmap.svelte';

  let { players = [] } = $props();

  let selected = $state('');
  let data = $state(null);
  let error = $state(false);

  let sortedNames = $derived([...new Set(players)].sort());

  $effect(() => {
    if (!selected && sortedNames.length) selected = sortedNames[0];
  });

  $effect(() => {
    if (selected) load(selected);
  });

  async function load(name) {
    error = false;
    try {
      data = await fetch(`/api/stats/dashboard/${encodeURIComponent(name)}?mode=elimination`).then((r) => r.json());
    } catch (e) {
      data = null;
      error = true;
    }
  }

  function recordSub(r, showTarget) {
    if (!r) return '';
    const date = new Date(r.date).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
    return `${showTarget ? `had to beat ${r.target} · ` : ''}${date}`;
  }
</script>

<div class="dash-controls">
  <label for="dashPlayerSelect">Player</label>
  <select id="dashPlayerSelect" bind:value={selected}>
    {#each sortedNames as name}
      <option value={name}>{cap(name)}</option>
    {/each}
  </select>
</div>

{#if !sortedNames.length}
  <div class="dv-empty">No players with stats yet — play a game first.</div>
{:else if error}
  <div class="dv-empty">Could not load dashboard.</div>
{:else if data}
  {@const a = data.activity}
  {@const rec = data.elimination_records}

  <div class="stat-tiles">
    <div class="stat-tile"><div class="stat-tile-label">Total darts</div><div class="stat-tile-value">{a.total_darts}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">Total playtime</div><div class="stat-tile-value">{a.total_playtime_hours.toFixed(2)}h</div></div>
    <div class="stat-tile"><div class="stat-tile-label">Total distance</div><div class="stat-tile-value">{a.total_distance_km.toFixed(2)}km</div></div>
  </div>
  <div class="stat-tiles records">
    <div class="stat-tile">
      <div class="stat-tile-label">Highest score</div>
      <div class="stat-tile-value">{rec.highest_score?.score ?? '—'}</div>
      <div class="stat-tile-sub">{recordSub(rec.highest_score, false)}</div>
    </div>
    <div class="stat-tile">
      <div class="stat-tile-label">Highest score that still lost a life</div>
      <div class="stat-tile-value">{rec.highest_lost_score?.score ?? '—'}</div>
      <div class="stat-tile-sub">{recordSub(rec.highest_lost_score, true)}</div>
    </div>
  </div>
  <div class="dash-charts-2col">
    <div class="dash-chart-card">
      <div class="dash-chart-title">Darts per day</div>
      <ActivityBars data={data.activity_by_date.map((r) => ({ label: r.date, value: r.darts }))} unit="darts" />
    </div>
    <div class="dash-chart-card">
      <div class="dash-chart-title">Minutes played per day</div>
      <ActivityBars data={data.activity_by_date.map((r) => ({ label: r.date, value: Math.round(r.minutes) }))} unit="min" />
    </div>
  </div>
  {#if data.dart_positions.total}
    <div class="dash-chart-card top">
      <div class="dash-chart-title">Dart positions</div>
      <PositionHeatmap darts={data.dart_positions.darts} corrected={data.dart_positions.corrected} />
    </div>
  {/if}
{/if}

<style>
  .dash-controls { display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.5rem; }
  .dash-controls label { font-size: 0.8rem; color: var(--muted); }
  .dash-controls select {
    background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); color: var(--text);
    border-radius: 8px; padding: 0.45rem 0.7rem; font-size: 0.9rem;
  }
  .stat-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 0.75rem; }
  .stat-tile {
    background: var(--glass); border: 1px solid var(--glass-border); border-radius: 12px; box-shadow: var(--glass-shadow);
    padding: 0.75rem 0.9rem; text-align: center;
  }
  .stat-tile-label { font-size: 0.7rem; color: var(--muted); margin-bottom: 0.3rem; }
  .stat-tile-value { font-size: 1.4rem; font-weight: 600; }
  .stat-tile-sub { font-size: 0.7rem; color: var(--muted); margin-top: 0.2rem; min-height: 1em; }
  .stat-tiles.records { margin-top: 0.75rem; grid-template-columns: 1fr 1fr; }
  .dash-charts-2col { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; margin-top: 0.75rem; }
  .dash-chart-card {
    background: var(--glass); border: 1px solid var(--glass-border); border-radius: 14px; box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur);
    padding: 0.75rem 0.9rem;
  }
  .dash-chart-card.top { margin-top: 0.75rem; }
  .dash-chart-title { font-size: 0.75rem; color: var(--muted); margin-bottom: 0.5rem; }
  .dv-empty { color: var(--muted); font-size: 0.8rem; text-align: center; padding: 1rem 0; }
  @media (max-width: 700px) {
    .dash-charts-2col { grid-template-columns: 1fr; }
  }
</style>
