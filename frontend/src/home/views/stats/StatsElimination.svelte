<script>
  // Elimination half of the Stats tab: lifetime Elimination numbers per
  // player, recent Elimination matches and the Elimination side of the
  // per-player dashboard.
  import { onMount } from 'svelte';
  import { cap } from '../../../lib/util.js';
  import Dashboard from '../Dashboard.svelte';
  import RecentMatches from './RecentMatches.svelte';

  let players = $state([]);
  let loadFailed = $state(false);

  onMount(async () => {
    try {
      players = await fetch('/api/stats/elimination/players').then((r) => r.json());
    } catch (e) {
      loadFailed = true;
    }
  });
</script>

<div class="section-title">Lifetime stats</div>
<table class="players-table stats-table">
  <thead>
    <tr>
      <th>Player</th><th class="num-cell">Games</th><th class="num-cell">Wins</th><th class="num-cell">Win %</th>
      <th class="num-cell">1st</th><th class="num-cell">2nd</th><th class="num-cell">3rd</th>
    </tr>
  </thead>
  <tbody>
    {#if loadFailed}
      <tr><td colspan="7" class="stats-empty">Could not load stats.</td></tr>
    {:else if !players.length}
      <tr><td colspan="7" class="stats-empty">No Elimination games yet — play one first.</td></tr>
    {:else}
      {#each players as p (p.player)}
        <tr>
          <td>{cap(p.player)}</td>
          <td class="num-cell">{p.games}</td>
          <td class="num-cell">{p.wins}</td>
          <td class="num-cell">{p.win_pct.toFixed(0)}%</td>
          <td class="num-cell">{p.placements.first}</td>
          <td class="num-cell">{p.placements.second}</td>
          <td class="num-cell">{p.placements.third}</td>
        </tr>
      {/each}
    {/if}
  </tbody>
</table>

<RecentMatches mode="elimination" />

<div class="section-title top2">Advanced</div>
<Dashboard mode="elimination" players={players.map((p) => p.player)} />

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
  .stats-empty { color: var(--muted); text-align: center; padding: 1.5rem 0; }
</style>
