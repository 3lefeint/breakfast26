<script>
  // X01 half of the Stats tab: only X01 numbers — lifetime table, recent
  // X01 matches, leaderboards and the X01 side of the per-player dashboard.
  import { onMount } from 'svelte';
  import { cap } from '../../../lib/util.js';
  import Dashboard from '../Dashboard.svelte';
  import RecentMatches from './RecentMatches.svelte';

  let players = $state([]);
  let lbAvg = $state([]);
  let lb180 = $state([]);
  let lbCo = $state([]);
  let lbDbl = $state([]);
  let loadFailed = $state(false);

  onMount(async () => {
    try {
      const [p, a, s180, co, dbl] = await Promise.all([
        fetch('/api/stats/players').then((r) => r.json()),
        fetch('/api/leaderboard?metric=avg3&limit=10').then((r) => r.json()),
        fetch('/api/leaderboard?metric=s180&limit=10').then((r) => r.json()),
        fetch('/api/leaderboard?metric=co_pct&limit=10').then((r) => r.json()),
        fetch('/api/leaderboard?metric=dbl_pct&limit=10').then((r) => r.json()),
      ]);
      players = p; lbAvg = a; lb180 = s180; lbCo = co; lbDbl = dbl;
    } catch (e) {
      loadFailed = true;
    }
  });
</script>

<div class="section-title">Lifetime stats</div>
<table class="players-table stats-table">
  <thead>
    <tr>
      <th>Player</th><th class="num-cell">Sessions</th><th class="num-cell">Avg</th>
      <th class="num-cell">180</th><th class="num-cell">140+</th><th class="num-cell">100+</th>
      <th class="num-cell">CO%</th><th class="num-cell">D%</th>
    </tr>
  </thead>
  <tbody>
    {#if loadFailed}
      <tr><td colspan="8" class="stats-empty">Could not load stats.</td></tr>
    {:else if !players.length}
      <tr><td colspan="8" class="stats-empty">No X01 data yet — play a game first.</td></tr>
    {:else}
      {#each players as p (p.player)}
        <tr>
          <td>{cap(p.player)}</td>
          <td class="num-cell">{p.sessions ?? '—'}</td>
          <td class="num-cell">{p.avg3 != null ? p.avg3.toFixed(1) : '—'}</td>
          <td class="num-cell">{p.s180 ?? '—'}</td>
          <td class="num-cell">{p.s140 ?? '—'}</td>
          <td class="num-cell">{p.s100 ?? '—'}</td>
          <td class="num-cell">{p.co_attempts ? p.co_pct + '%' : '—'}</td>
          <td class="num-cell">{p.dbl_attempts ? p.dbl_pct + '%' : '—'}</td>
        </tr>
      {/each}
    {/if}
  </tbody>
</table>

<RecentMatches mode="x01" />

<div class="section-title top2">Leaderboard</div>
<div class="leaderboard-grid">
  <div>
    <div class="lb-label">Best Average</div>
    <table class="players-table stats-table"><thead><tr><th>#</th><th>Player</th><th class="num-cell">Avg</th></tr></thead>
      <tbody>
        {#if !lbAvg.length}<tr><td colspan="3" class="stats-empty">—</td></tr>{/if}
        {#each lbAvg as r, i}<tr><td class="num-cell muted narrow">#{i + 1}</td><td>{cap(r.player)}</td><td class="num-cell">{r.avg3 != null ? r.avg3.toFixed(1) : '—'}</td></tr>{/each}
      </tbody>
    </table>
  </div>
  <div>
    <div class="lb-label">Most 180s</div>
    <table class="players-table stats-table"><thead><tr><th>#</th><th>Player</th><th class="num-cell">180s</th></tr></thead>
      <tbody>
        {#if !lb180.length}<tr><td colspan="3" class="stats-empty">—</td></tr>{/if}
        {#each lb180 as r, i}<tr><td class="num-cell muted narrow">#{i + 1}</td><td>{cap(r.player)}</td><td class="num-cell">{r.s180 ?? '—'}</td></tr>{/each}
      </tbody>
    </table>
  </div>
  <div>
    <div class="lb-label">Best Checkout %</div>
    <table class="players-table stats-table"><thead><tr><th>#</th><th>Player</th><th class="num-cell">CO%</th></tr></thead>
      <tbody>
        {#if !lbCo.length}<tr><td colspan="3" class="stats-empty">—</td></tr>{/if}
        {#each lbCo as r, i}<tr><td class="num-cell muted narrow">#{i + 1}</td><td>{cap(r.player)}</td><td class="num-cell">{r.co_attempts ? r.co_pct + '%' : '—'}</td></tr>{/each}
      </tbody>
    </table>
  </div>
  <div>
    <div class="lb-label">Best Double %</div>
    <table class="players-table stats-table"><thead><tr><th>#</th><th>Player</th><th class="num-cell">D%</th></tr></thead>
      <tbody>
        {#if !lbDbl.length}<tr><td colspan="3" class="stats-empty">—</td></tr>{/if}
        {#each lbDbl as r, i}<tr><td class="num-cell muted narrow">#{i + 1}</td><td>{cap(r.player)}</td><td class="num-cell">{r.dbl_attempts ? r.dbl_pct + '%' : '—'}</td></tr>{/each}
      </tbody>
    </table>
  </div>
</div>

<div class="section-title top2">Advanced</div>
<Dashboard mode="x01" players={players.map((p) => p.player)} />

<style>
  .section-title { font-size: 0.8rem; color: var(--muted); margin: 0 0 0.5rem; letter-spacing: 0.06em; text-transform: uppercase; }
  .section-title.top2 { margin-top: 2rem; }
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
  .stats-empty { color: var(--muted); text-align: center; padding: 1.5rem 0; }
  .leaderboard-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-top: 0.5rem; }
  .lb-label { font-size: 0.8rem; color: var(--muted); margin-bottom: 0.4rem; }
</style>
