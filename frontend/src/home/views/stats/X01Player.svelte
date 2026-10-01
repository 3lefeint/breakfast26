<script>
  // The X01 side of the per-player section: a player picker, activity and
  // performance tiles, the spread of the turn scores, win/loss and the average
  // per match, the checkout % per match, the doubles, the fastest legs and the highest
  // checkouts.
  import { cap } from '../../../lib/util.js';
  import ActivityBars from './ActivityBars.svelte';
  import Histogram from './Histogram.svelte';
  import Donut from './Donut.svelte';
  import TrendLine from './TrendLine.svelte';
  import DartHeatmap from './DartHeatmap.svelte';
  import BustBands from './BustBands.svelte';
  import DoublesRadar from './DoublesRadar.svelte';
  import RankBars from './RankBars.svelte';
  import TopLegs from './TopLegs.svelte';
  import TopCheckouts from './TopCheckouts.svelte';

  let { players = [] } = $props();

  let selected = $state('');
  let data = $state(null);
  let error = $state(false);

  let names = $derived([...new Set(players)].sort());

  $effect(() => { if (!selected && names.length) selected = names[0]; });
  $effect(() => { if (selected) load(selected); });

  async function load(name, pointsStart = null) {
    error = false;
    try {
      const params = new URLSearchParams({ mode: 'x01' });
      if (pointsStart != null) params.set('points_start', pointsStart);
      data = await fetch(`/api/stats/dashboard/${encodeURIComponent(name)}?${params}`).then((r) => r.json());
    } catch (e) {
      data = null;
      error = true;
    }
  }

  const fmtPct = (v) => v.toFixed(0) + '%';

  // The dart fields boiled down: what kind of dart it was and which fields were hit most.
  function hitStats(h) {
    const sum = (test) => Object.entries(h.fields).filter(([f]) => test(f)).reduce((a, [, n]) => a + n, 0);
    const missed = Object.values(h.misses).reduce((a, n) => a + n, 0) + h.no_sector_misses;
    const row = (name, value) => ({ name, value, text: String(value), sub: `${((value / h.darts) * 100).toFixed(0)}%` });
    const kinds = [
      row('Singles', sum((f) => f.startsWith('S'))), row('Doubles', sum((f) => f.startsWith('D'))),
      row('Triples', sum((f) => f.startsWith('T'))), row('Bull', sum((f) => f === 'BULL' || f === '25')),
      row('Missed', missed),
    ].sort((a, b) => b.value - a.value);
    const top = Object.entries(h.fields).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 5)
      .map(([f, n]) => row(f === 'BULL' ? 'Bull (50)' : f, n));
    return { missed, kinds, top, missRate: h.darts ? (missed / h.darts) * 100 : 0 };
  }
</script>

<div class="controls">
  <label for="x01PlayerSelect">Player</label>
  <select id="x01PlayerSelect" bind:value={selected}>
    {#each names as name}<option value={name}>{cap(name)}</option>{/each}
  </select>
</div>

{#if !names.length}
  <div class="empty">No players with stats yet — play a game first.</div>
{:else if error}
  <div class="empty">Could not load the player.</div>
{:else if data}
  {@const a = data.activity}
  {@const p = data.performance}
  {@const wl = data.win_loss}

  <div class="subtitle">Activity</div>
  <div class="tiles">
    <div class="tile"><div class="label">Total darts</div><div class="value">{a.total_darts}</div></div>
    <div class="tile"><div class="label">Matches</div><div class="value">{a.total_games}</div></div>
    <div class="tile"><div class="label">Total playtime</div><div class="value">{a.total_playtime_hours.toFixed(2)}h</div></div>
    <div class="tile"><div class="label">Total distance</div><div class="value">{a.total_distance_km.toFixed(2)}km</div></div>
  </div>
  <div class="two">
    <div class="card">
      <div class="card-title">Darts per day played</div>
      <ActivityBars data={data.activity_by_date.map((r) => ({ label: r.date, value: r.darts }))} unit="darts" />
    </div>
    <div class="card">
      <div class="card-title">Minutes per day played</div>
      <ActivityBars data={data.activity_by_date.map((r) => ({ label: r.date, value: Math.round(r.minutes) }))} unit="min" />
    </div>
  </div>

  <div class="subtitle">Performance</div>
  <div class="tiles">
    <div class="tile"><div class="label">Best average</div><div class="value">{p.best_avg3.toFixed(1)}</div></div>
    <div class="tile"><div class="label">Best leg 501</div><div class="value">{p.best_leg_501_darts != null ? p.best_leg_501_darts + ' darts' : '—'}</div></div>
    <div class="tile"><div class="label">Best checkout</div><div class="value">{p.best_checkout ?? '—'}</div></div>
    <div class="tile"><div class="label">Total 180s</div><div class="value">{p.total_180s}</div></div>
  </div>
  <div class="card top uni">
    <div class="card-title">Points per turn</div>
    <div class="middle"><Histogram bins={data.score_histogram.bins} mean={data.score_histogram.avg3} /></div>
  </div>
  {@const h = hitStats(data.dart_hits)}
  <div class="board-row top">
    <div class="side">
      <div class="tiles two-tiles">
        <div class="tile"><div class="label">Darts thrown</div><div class="value">{data.dart_hits.darts}</div></div>
        <div class="tile"><div class="label">Missed the board</div><div class="value">{h.missRate.toFixed(0)}%</div></div>
      </div>
      <div class="card">
        <div class="card-title">Heatmap</div>
        <DartHeatmap fields={data.dart_hits.fields} misses={data.dart_hits.misses} darts={data.dart_hits.darts} />
      </div>
    </div>
    <div class="side">
      <RankBars title="Darts by kind" rows={h.kinds} large />
      <RankBars title="Most hit fields" rows={h.top} large />
    </div>
  </div>
  {@const bust = data.bust_by_remaining}
  <div class="card top uni">
    <div class="card-title">Bust rate</div>
    <div class="middle"><BustBands bands={bust.bands} /></div>
    <div class="card-note">Games from before the fix miss the bust dart itself and busts on the first dart, so their rates are a lower bound.</div>
  </div>
  <div class="two">
    <div class="card uni">
      <div class="card-title">Win / Loss</div>
      <div class="middle">
        <Donut
          segments={[
            { label: 'Wins', value: wl.wins, color: 'var(--accent)' },
            { label: 'Losses', value: wl.losses, color: 'var(--muted)' },
          ]}
          centerValue={wl.wins + wl.losses ? fmtPct((wl.wins / (wl.wins + wl.losses)) * 100) : ''}
          centerLabel="{wl.wins} W · {wl.losses} L" />
      </div>
    </div>
    <div class="card uni">
      <div class="card-title">Average over time</div>
      <div class="middle">
        <TrendLine yTitle="avg 3 darts"
          points={data.avg_by_match.map((m) => ({
            date: m.started_at, value: m.avg3,
            tip: `${new Date(m.started_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })} · ${m.avg3.toFixed(1)} · ${m.darts} darts${m.points_start ? ' · ' + m.points_start : ''}`,
          }))} />
      </div>
    </div>
  </div>

  <div class="two">
    <div class="card uni">
      <div class="card-title">Doubles</div>
      <div class="middle"><DoublesRadar doubles={data.doubles} /></div>
    </div>
    <div class="card uni">
      <div class="card-title">Checkout %</div>
      <div class="middle">
        <TrendLine unit="%" decimals={0}
          points={data.checkout_by_match.map((m) => ({
            date: m.started_at, value: m.co_pct,
            tip: `${new Date(m.started_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })} · ${m.co_pct.toFixed(0)}% · ${m.hits}/${m.attempts}`,
          }))} />
      </div>
    </div>
  </div>

  <div class="card top uni">
    <div class="card-title">Top 10 legs</div>
    {#if !data.leg_modes.length}
      <div class="empty">No legs won yet.</div>
    {:else}
      <div class="mode-tabs">
        {#each data.leg_modes as m}
          <button type="button" class="mode-tab" class:active={m === data.selected_points_start} onclick={() => load(selected, m)}>{m}</button>
        {/each}
      </div>
      <div class="middle"><TopLegs legs={data.top_legs} /></div>
    {/if}
  </div>

  <div class="card top uni">
    <div class="card-title">Top 10 checkouts</div>
    {#if !data.top_checkouts.length}
      <div class="empty">No checkouts recorded yet.</div>
    {:else}
      <div class="middle"><TopCheckouts checkouts={data.top_checkouts} /></div>
    {/if}
  </div>
{/if}

<style>
  .controls { display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.5rem; }
  .controls label { font-size: 0.8rem; color: var(--muted); }
  .controls select { background: var(--bg); border: 1px solid var(--border); color: var(--text); border-radius: 8px; padding: 0.45rem 0.7rem; font-size: 0.9rem; }
  .subtitle { font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; margin: 1.5rem 0 0.6rem; }
  .empty { color: var(--muted); font-size: 0.8rem; text-align: center; padding: 1rem 0; }
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 0.75rem; }
  .tile { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 0.75rem 0.9rem; text-align: center; }
  .tile .label { font-size: 0.7rem; color: var(--muted); margin-bottom: 0.3rem; }
  .tile .value { font-size: 1.4rem; font-weight: 600; }
  .two { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 0.75rem; margin-top: 0.75rem; }
  .board-row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 0.75rem; }
  .board-row.top { margin-top: 0.75rem; }
  .side { display: flex; flex-direction: column; gap: 0.75rem; }
  .side > :global(.card) { flex: 1; }
  .two-tiles { grid-template-columns: 1fr 1fr; }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 0.75rem 0.9rem; }
  .card.top { margin-top: 0.75rem; }
  .card.uni { display: flex; flex-direction: column; height: 30rem; box-sizing: border-box; }
  .middle { flex: 1; min-height: 0; display: flex; align-items: center; justify-content: center; }
  .middle > :global(svg) { max-height: 100%; }
  .middle > :global(.donut) { align-self: stretch; }
  .middle > :global(.radar) { align-self: stretch; }
  .card-title { font-size: 0.75rem; color: var(--muted); margin-bottom: 0.5rem; }
  .card-note { font-size: 0.7rem; color: var(--muted); margin-top: 0.4rem; }
  .mode-tabs { display: flex; gap: 0.4rem; margin-bottom: 0.6rem; }
  .mode-tab { background: var(--bg); border: 1px solid var(--border); color: var(--muted); border-radius: 20px; padding: 0.3rem 0.8rem; font-family: inherit; font-size: 0.85rem; cursor: pointer; }
  .mode-tab:hover { border-color: var(--accent); color: var(--text); }
  .mode-tab.active { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); font-weight: 700; }
  @media (max-width: 700px) { .two, .board-row { grid-template-columns: 1fr; } }
</style>
