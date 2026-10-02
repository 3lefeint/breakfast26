<script>
  // X01 half of the Stats tab: totals and records, the players compared as bars,
  // recent X01 matches and the per-player section.
  import { onMount } from 'svelte';
  import { cap } from '../../../lib/util.js';
  import X01Player from './X01Player.svelte';
  import RecentMatches from './RecentMatches.svelte';
  import RankBars from './RankBars.svelte';

  let players = $state([]);
  let overview = $state(null);
  let loadFailed = $state(false);

  onMount(async () => {
    try {
      [players, overview] = await Promise.all([
        fetch('/api/stats/players').then((r) => r.json()),
        fetch('/api/stats/x01/overview').then((r) => r.json()),
      ]);
    } catch (e) {
      loadFailed = true;
    }
  });

  const date = (iso) => new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
  const who = (r) => (r ? `${cap(r.player)} · ${date(r.date)}` : '');
  const hours = (h) => (h < 1 ? `${Math.round(h * 60)} min` : `${h.toFixed(1)} h`);

  // Best first; each ranking only lists players it can say something about.
  function ranking(list, value, text, sub) {
    return list
      .map((p) => ({ name: cap(p.player), value: value(p), text: text(p), sub: sub?.(p) }))
      .sort((a, b) => b.value - a.value);
  }
  let rankings = $derived({
    average: ranking(players.filter((p) => p.avg3 != null), (p) => p.avg3, (p) => p.avg3.toFixed(1), (p) => `${p.turns} turns`),
    tons: ranking(players, (p) => p.s100 + p.s140 + p.s180, (p) => `${p.s100 + p.s140 + p.s180}`, (p) => `of ${p.turns}`),
    checkout: ranking(players.filter((p) => p.co_attempts), (p) => p.co_pct, (p) => `${p.co_pct}%`, (p) => `${p.co_hits}/${p.co_attempts}`),
  });
</script>

{#if loadFailed}
  <div class="empty">Could not load stats.</div>
{:else if overview}
  {@const s = overview.summary}
  {@const r = overview.records}
  <div class="section-title">Overview</div>
  <div class="stat-tiles">
    <div class="stat-tile"><div class="stat-tile-label">Matches</div><div class="stat-tile-value">{s.matches}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">Legs</div><div class="stat-tile-value">{s.legs}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">Total darts</div><div class="stat-tile-value">{s.darts}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">Total playtime</div><div class="stat-tile-value">{hours(s.playtime_hours)}</div></div>
  </div>
  <div class="records">
    <div class="record">
      <div class="stat-tile-label">Highest turn</div>
      <div class="stat-tile-value">{r.highest_turn?.score ?? '—'}</div>
      <div class="record-sub">{who(r.highest_turn)}</div>
    </div>
    <div class="record">
      <div class="stat-tile-label">Highest checkout</div>
      <div class="stat-tile-value">{r.highest_checkout?.score ?? '—'}</div>
      <div class="record-sub">{r.highest_checkout ? r.highest_checkout.targets.join(' ') + ' · ' : ''}{who(r.highest_checkout)}</div>
    </div>
    <div class="record">
      <div class="stat-tile-label">Best leg{r.best_leg ? ` (${r.best_leg.points_start})` : ''}</div>
      <div class="stat-tile-value">{r.best_leg ? `${r.best_leg.darts} darts` : '—'}</div>
      <div class="record-sub">{who(r.best_leg)}</div>
    </div>
    <div class="record">
      <div class="stat-tile-label">Best match average</div>
      <div class="stat-tile-value">{r.best_average ? r.best_average.avg3.toFixed(1) : '—'}</div>
      <div class="record-sub">{who(r.best_average)}</div>
    </div>
  </div>

  <div class="section-title top">Players compared</div>
  <div class="rankings">
    <RankBars title="Average (3 darts)" rows={rankings.average} />
    <RankBars title="Turns of 100 or more" rows={rankings.tons} />
    <RankBars title="Checkout %" rows={rankings.checkout} />
  </div>
{/if}

<RecentMatches mode="x01" />

<div class="section-title top2">Player</div>
<X01Player players={players.map((p) => p.player)} />

<style>
  .section-title { font-size: 0.8rem; color: var(--muted); margin: 0 0 0.6rem; letter-spacing: 0.06em; text-transform: uppercase; }
  .section-title.top { margin-top: 1.75rem; }
  .section-title.top2 { margin-top: 2rem; }
  .empty { color: var(--muted); text-align: center; padding: 1.5rem 0; }
  .stat-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 0.75rem; }
  .stat-tile, .record {
    background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
    padding: 0.75rem 0.9rem; text-align: center;
  }
  .stat-tile-label { font-size: 0.7rem; color: var(--muted); margin-bottom: 0.3rem; }
  .stat-tile-value { font-size: 1.4rem; font-weight: 600; }
  .records { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; margin-top: 0.75rem; }
  .record-sub { font-size: 0.75rem; color: var(--muted); margin-top: 0.2rem; min-height: 1em; }
  .rankings { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; }
  @media (max-width: 700px) { .rankings, .records { grid-template-columns: 1fr; } }
</style>
