<script>
  // Ports index.html's Advanced dashboard: player selector +
  // renderDashboard()'s full set of stat tiles/charts/tables, one bundled
  // fetch per player via /api/stats/dashboard/{name}.
  import { cap } from '../../lib/util.js';
  import BarChart from '../../lib/components/charts/BarChart.svelte';
  import LineChart from '../../lib/components/charts/LineChart.svelte';
  import HBarChart from '../../lib/components/charts/HBarChart.svelte';
  import ProportionBar from '../../lib/components/charts/ProportionBar.svelte';

  // mode: 'x01' or 'elimination'.
  let { players = [], mode } = $props();
  let showX01 = $derived(mode !== 'elimination');
  let showElimination = $derived(mode !== 'x01');

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

  async function load(name, pointsStart = null) {
    error = false;
    try {
      const params = new URLSearchParams({ mode });
      if (pointsStart != null) params.set('points_start', pointsStart);
      data = await fetch(`/api/stats/dashboard/${encodeURIComponent(name)}?${params}`).then((r) => r.json());
    } catch (e) {
      data = null;
      error = true;
    }
  }

  function selectLegMode(pointsStart) {
    load(selected, pointsStart);
  }

  function fmtPct(v) { return v.toFixed(0) + '%'; }
  function fmtAvg(v) { return v.toFixed(1); }
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
  {@const p = data.performance}

  <div class="dash-subtitle">Activity</div>
  <div class="stat-tiles">
    <div class="stat-tile"><div class="stat-tile-label">Total darts</div><div class="stat-tile-value">{a.total_darts}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">Total games</div><div class="stat-tile-value">{a.total_games}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">Total playtime</div><div class="stat-tile-value">{a.total_playtime_hours.toFixed(2)}h</div></div>
    <div class="stat-tile"><div class="stat-tile-label">Total distance</div><div class="stat-tile-value">{a.total_distance_km.toFixed(2)}km</div></div>
  </div>
  <div class="dash-charts-2col">
    <div class="dash-chart-card">
      <div class="dash-chart-title">Darts per day</div>
      <BarChart data={data.activity_by_date.map((r) => ({ label: r.date, value: r.darts }))} />
    </div>
    <div class="dash-chart-card">
      <div class="dash-chart-title">Minutes played per day</div>
      <BarChart data={data.activity_by_date.map((r) => ({ label: r.date, value: Math.round(r.minutes) }))} />
    </div>
  </div>

  {#if showX01}
  <div class="dash-subtitle">Performance</div>
  <div class="stat-tiles">
    <div class="stat-tile"><div class="stat-tile-label">Best average</div><div class="stat-tile-value">{p.best_avg3.toFixed(1)}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">Best leg</div><div class="stat-tile-value">{p.best_leg_darts != null ? p.best_leg_darts + ' darts' : '—'}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">Best checkout</div><div class="stat-tile-value">{p.best_checkout ?? '—'}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">Total 180s</div><div class="stat-tile-value">{p.total_180s}</div></div>
  </div>
  <div class="dash-chart-card top">
    <div class="dash-chart-title">Scoring</div>
    <HBarChart data={[
      { label: '<60', value: data.scoring_buckets.under_60 },
      { label: '60-99', value: data.scoring_buckets['60_99'] },
      { label: '100-139', value: data.scoring_buckets['100_139'] },
      { label: '140-169', value: data.scoring_buckets['140_169'] },
      { label: '170+', value: data.scoring_buckets['170_plus'] },
    ]} />
  </div>
  <div class="dash-charts-2col">
    <div class="dash-chart-card">
      <div class="dash-chart-title">Average over time</div>
      <LineChart data={data.avg_by_date.map((r) => ({ label: r.date, value: r.avg3 }))} formatValue={fmtAvg} />
    </div>
    <div class="dash-chart-card">
      <div class="dash-chart-title">Checkout % over time</div>
      <LineChart data={data.checkout_pct_by_date.map((r) => ({ label: r.date, value: r.co_pct }))} formatValue={fmtPct} />
    </div>
  </div>
  {/if}

  <div class="dash-charts-2col">
    <div class="dash-chart-card">
      <div class="dash-chart-title">Win / loss ({data.win_loss.wins}W &middot; {data.win_loss.losses}L)</div>
      <ProportionBar segments={[
        { label: 'Wins', value: data.win_loss.wins, color: 'var(--green)' },
        { label: 'Losses', value: data.win_loss.losses, color: 'var(--red)' },
      ]} />
    </div>
  </div>

  {#if showElimination && data.elimination?.games}
    {@const e = data.elimination}
    <div class="dash-subtitle">Elimination</div>
    <div class="stat-tiles">
      <div class="stat-tile"><div class="stat-tile-label">Games</div><div class="stat-tile-value">{e.games}</div></div>
      <div class="stat-tile"><div class="stat-tile-label">Wins</div><div class="stat-tile-value">{e.wins}</div></div>
      <div class="stat-tile"><div class="stat-tile-label">Win rate</div><div class="stat-tile-value">{fmtPct(e.win_pct)}</div></div>
      <div class="stat-tile"><div class="stat-tile-label">Avg darts / turn</div><div class="stat-tile-value">{e.avg_darts_per_turn != null ? e.avg_darts_per_turn.toFixed(1) : '—'}</div></div>
    </div>
    <div class="dash-chart-card top">
      <div class="dash-chart-title">Placements ({e.placements.first} 1st &middot; {e.placements.second} 2nd &middot; {e.placements.third} 3rd &middot; {e.placements.other} lower)</div>
      <ProportionBar segments={[
        { label: '1st', value: e.placements.first, color: 'var(--green)' },
        { label: '2nd', value: e.placements.second, color: 'var(--accent)' },
        { label: '3rd', value: e.placements.third, color: 'var(--muted)' },
        { label: 'Lower', value: e.placements.other, color: 'var(--red)' },
      ]} />
    </div>
  {/if}

  {#if showX01}
  <div class="dash-chart-card top">
    <div class="dash-chart-title">Doubles hit rate</div>
    <HBarChart
      data={data.doubles.map((r) => ({ label: r.target == 25 ? 'Bull' : 'D' + r.target, value: r.pct, sub: `${r.hits}/${r.attempts}` }))}
      formatValue={(v, row) => `${row.sub} (${v.toFixed(0)}%)`}
    />
  </div>

  <div class="dash-subtitle">Top 10 legs</div>
  {#if data.leg_modes.length}
    <div class="mode-tabs">
      {#each data.leg_modes as m}
        <button type="button" class="mode-tab" class:active={m === data.selected_points_start} onclick={() => selectLegMode(m)}>{m}</button>
      {/each}
    </div>
  {/if}
  {#if !data.top_legs.length}
    <div class="dv-empty">No legs won yet at this mode.</div>
  {:else}
    <table class="players-table stats-table">
      <thead><tr><th>#</th><th class="num-cell">Darts</th><th class="num-cell">Avg</th></tr></thead>
      <tbody>
        {#each data.top_legs as l, i}
          <tr>
            <td class="num-cell muted narrow">#{i + 1}</td>
            <td class="num-cell">{l.darts}</td>
            <td class="num-cell">{l.avg3.toFixed(1)}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}

  <div class="dash-subtitle">Top 10 checkouts</div>
  {#if !data.top_checkouts.length}
    <div class="dv-empty">No checkouts recorded yet.</div>
  {:else}
    <table class="players-table stats-table">
      <thead><tr><th>#</th><th class="num-cell">Score</th><th>Targets</th><th>Type</th></tr></thead>
      <tbody>
        {#each data.top_checkouts as c, i}
          <tr>
            <td class="num-cell muted narrow">#{i + 1}</td>
            <td class="num-cell">{c.score}</td>
            <td>
              <div class="dart-chips">
                {#each c.targets as t}
                  <span class="dart-chip">{t}</span>
                {/each}
              </div>
            </td>
            <td>{c.points_start}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
  {/if}
{/if}

<style>
  .dash-controls { display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.5rem; }
  .dash-controls label { font-size: 0.8rem; color: var(--muted); }
  .dash-controls select {
    background: var(--bg); border: 1px solid var(--border); color: var(--text);
    border-radius: 8px; padding: 0.45rem 0.7rem; font-size: 0.9rem;
  }
  .dash-subtitle {
    font-size: 0.8rem; color: var(--muted); font-weight: 600;
    letter-spacing: 0.06em; text-transform: uppercase; margin: 1.5rem 0 0.6rem;
  }
  .mode-tabs { display: flex; gap: 0.4rem; margin-bottom: 0.6rem; }
  .mode-tab {
    background: var(--bg); border: 1px solid var(--border); color: var(--muted);
    border-radius: 20px; padding: 0.3rem 0.8rem; font-family: inherit;
    font-size: 0.85rem; cursor: pointer;
  }
  .mode-tab:hover { border-color: var(--accent); color: var(--text); }
  .mode-tab.active { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); font-weight: 700; }
  .dart-chips { display: flex; gap: 0.3rem; }
  .dart-chip {
    display: inline-flex; align-items: center; justify-content: center;
    min-width: 2.4rem; height: 1.6rem; padding: 0 0.35rem; box-sizing: border-box;
    background: var(--bg); border: 1px solid var(--border); border-radius: 6px;
    font-size: 0.75rem; font-variant-numeric: tabular-nums;
  }
  .stat-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 0.75rem; }
  .stat-tile {
    background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
    padding: 0.75rem 0.9rem; text-align: center;
  }
  .stat-tile-label { font-size: 0.7rem; color: var(--muted); margin-bottom: 0.3rem; }
  .stat-tile-value { font-size: 1.4rem; font-weight: 600; }
  .dash-charts-2col { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; margin-top: 0.75rem; }
  .dash-chart-card {
    background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
    padding: 0.75rem 0.9rem;
  }
  .dash-chart-card.top { margin-top: 0.75rem; }
  .dash-chart-title { font-size: 0.75rem; color: var(--muted); margin-bottom: 0.5rem; }
  .dv-empty { color: var(--muted); font-size: 0.8rem; text-align: center; padding: 1rem 0; }
  @media (max-width: 700px) {
    .dash-charts-2col { grid-template-columns: 1fr; }
  }
  .players-table { width: 100%; border-collapse: collapse; }
  .players-table th {
    font-size: 0.75rem; color: var(--muted); font-weight: 500;
    text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid var(--border);
  }
  .players-table td { padding: 0.55rem 0.6rem; border-bottom: 1px solid var(--border); }
  .stats-table th, .stats-table td { font-size: 0.8rem; }
  .num-cell { text-align: right; }
  .players-table th.num-cell { text-align: right; }
  .muted { color: var(--muted); }
  .narrow { width: 2rem; }
</style>
