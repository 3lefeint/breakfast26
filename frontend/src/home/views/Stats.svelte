<script>
  // Ports index.html's #view-stats: lifetime stats table, recent matches
  // (expandable per-match detail), leaderboard grid, and the Advanced
  // per-player dashboard (delegated to Dashboard.svelte).
  import { onMount } from 'svelte';
  import { cap } from '../../lib/util.js';
  import Dashboard from './Dashboard.svelte';
  import PageHeader from '../../lib/components/PageHeader.svelte';

  let players = $state([]);
  let matches = $state([]);
  let lbAvg = $state([]);
  let lb180 = $state([]);
  let lbCo = $state([]);
  let lbDbl = $state([]);
  let loadFailed = $state(false);

  let openMatches = $state(new Set());
  let matchDetails = $state({});
  let recentMatchesOpen = $state(false);

  onMount(loadStats);

  async function loadStats() {
    try {
      const [p, m, a, s180, co, dbl] = await Promise.all([
        fetch('/api/stats/players').then((r) => r.json()),
        fetch('/api/stats/matches').then((r) => r.json()),
        fetch('/api/leaderboard?metric=avg3&limit=10').then((r) => r.json()),
        fetch('/api/leaderboard?metric=s180&limit=10').then((r) => r.json()),
        fetch('/api/leaderboard?metric=co_pct&limit=10').then((r) => r.json()),
        fetch('/api/leaderboard?metric=dbl_pct&limit=10').then((r) => r.json()),
      ]);
      players = p; matches = m; lbAvg = a; lb180 = s180; lbCo = co; lbDbl = dbl;
      loadFailed = false;
    } catch (e) {
      loadFailed = true;
    }
  }

  async function deletePlayerStats(name) {
    if (!confirm(`Delete ALL stats for "${name}"?\n\nThis action cannot be undone.`)) return;
    if (!confirm(`Are you absolutely sure?\nAll data for "${name}" will be permanently deleted.`)) return;
    try {
      const r = await fetch(`/api/stats/player/${encodeURIComponent(name)}`, { method: 'DELETE' });
      if ((await r.json()).ok) loadStats();
    } catch (e) {
      alert('Delete failed: ' + e);
    }
  }

  async function toggleMatchDetail(matchId) {
    const next = new Set(openMatches);
    if (next.has(matchId)) {
      next.delete(matchId);
      openMatches = next;
      return;
    }
    if (!matchDetails[matchId]) {
      try {
        const data = await fetch(`/api/stats/match/${matchId}`).then((r) => r.json());
        matchDetails = { ...matchDetails, [matchId]: data };
      } catch (e) {
        matchDetails = { ...matchDetails, [matchId]: null };
      }
    }
    next.add(matchId);
    openMatches = next;
  }

  function ordinal(n) {
    if (n == null) return '—';
    const mod100 = n % 100;
    const suffix = mod100 >= 11 && mod100 <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th');
    return n + suffix;
  }
  function matchDate(m) { return m.started_at ? new Date(m.started_at).toLocaleString() : '?'; }
  function matchMode(m) { return [m.game_mode, m.points_start ? m.points_start + ' pts' : ''].filter(Boolean).join(' '); }
  function matchPlayers(m) { return (m.players || []).map(cap).join(' · '); }
  function legsLine(m) {
    const lw = m.legs_won || {};
    const lt = m.legs_total || 0;
    const parts = Object.entries(lw).map(([n, c]) => `${cap(n)} ${c}`).join(' · ');
    const suffix = lt > 0 ? `  (${lt} leg${lt !== 1 ? 's' : ''})` : '';
    return parts ? parts + suffix : '';
  }
</script>

<PageHeader title="Stats" />

<div class="section-title">Lifetime stats</div>
<table class="players-table stats-table">
  <thead>
    <tr>
      <th>Player</th><th class="num-cell">Sessions</th><th class="num-cell">Avg</th>
      <th class="num-cell">180</th><th class="num-cell">140+</th><th class="num-cell">100+</th>
      <th class="num-cell">CO%</th><th class="num-cell">D%</th><th></th>
    </tr>
  </thead>
  <tbody>
    {#if loadFailed}
      <tr><td colspan="9" class="stats-empty">Could not load stats.</td></tr>
    {:else if !players.length}
      <tr><td colspan="9" class="stats-empty">No data yet — play a game first.</td></tr>
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
          <td><button class="btn-del" onclick={() => deletePlayerStats(p.player)}>✕</button></td>
        </tr>
      {/each}
    {/if}
  </tbody>
</table>

<button type="button" class="section-title top collapsible-title" onclick={() => recentMatchesOpen = !recentMatchesOpen}>
  <span class="chevron" class:open={recentMatchesOpen}>▸</span> Recent matches
</button>
{#if recentMatchesOpen}
<div class="stats-matches">
  {#if !matches.length}
    <div class="stats-empty">No matches recorded yet.</div>
  {:else}
    {#each matches as m (m.match_id)}
      <div class="stats-match-card" role="button" tabindex="0"
           onclick={() => toggleMatchDetail(m.match_id)}
           onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && toggleMatchDetail(m.match_id)}>
        <div class="stats-match-meta">{matchDate(m)}  ·  {matchMode(m)}</div>
        <div class="stats-match-players">{matchPlayers(m) || '—'}</div>
        {#if legsLine(m)}
          <div class="stats-match-meta legs">{legsLine(m)}</div>
        {/if}
        {#if openMatches.has(m.match_id)}
          <div class="stats-match-detail open">
            {#if matchDetails[m.match_id] == null}
              <div class="stats-empty">Load failed.</div>
            {:else}
              {#if m.game_mode === 'Elimination'}
                <table class="players-table stats-table detail">
                  <thead><tr><th>Player</th><th class="num-cell">Place</th><th class="num-cell">Lives left</th><th class="num-cell">Turns</th><th class="num-cell">Avg darts</th></tr></thead>
                  <tbody>
                    {#each Object.entries(matchDetails[m.match_id]) as [name, s]}
                      <tr>
                        <td>{cap(name)}</td>
                        <td class="num-cell">{ordinal(s.placement)}</td>
                        <td class="num-cell">{s.lives_left ?? '—'}</td>
                        <td class="num-cell">{s.turns}</td>
                        <td class="num-cell">{s.avg_darts_per_turn != null ? s.avg_darts_per_turn.toFixed(1) : '—'}</td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              {:else}
              <table class="players-table stats-table detail">
                <thead><tr><th>Player</th><th class="num-cell">Avg</th><th class="num-cell">180</th><th class="num-cell">CO%</th><th class="num-cell">D%</th></tr></thead>
                <tbody>
                  {#each Object.entries(matchDetails[m.match_id]) as [name, s]}
                    <tr>
                      <td>{cap(name)}</td>
                      <td class="num-cell">{s.avg3 != null ? s.avg3.toFixed(1) : '—'}</td>
                      <td class="num-cell">{s.s180 ?? '—'}</td>
                      <td class="num-cell">{s.co_attempts ? s.co_pct + '%' : '—'}</td>
                      <td class="num-cell">{s.dbl_attempts ? s.dbl_pct + '%' : '—'}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
              {/if}
            {/if}
          </div>
        {/if}
      </div>
    {/each}
  {/if}
</div>
{/if}

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
<Dashboard players={players.map((p) => p.player)} />

<style>
  .section-title { font-size: 0.8rem; color: var(--muted); margin: 0 0 0.5rem; letter-spacing: 0.06em; text-transform: uppercase; }
  .section-title.top { margin-top: 1.5rem; }
  .section-title.top2 { margin-top: 2rem; }
  .collapsible-title {
    display: flex; align-items: center; gap: 0.4rem;
    background: none; border: none; padding: 0; font-family: inherit;
    cursor: pointer; width: 100%; text-align: left;
  }
  .collapsible-title:hover { color: var(--text); }
  .chevron { display: inline-block; font-size: 0.7rem; transition: transform 0.15s; }
  .chevron.open { transform: rotate(90deg); }
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
  .btn-del { background: transparent; border: 1px solid var(--border); color: var(--muted); font-size: 0.7rem; padding: 0.15rem 0.4rem; border-radius: 4px; cursor: pointer; }
  .btn-del:hover { border-color: #ef4444; color: #ef4444; }
  .stats-matches { display: flex; flex-direction: column; gap: 0.5rem; }
  .stats-match-card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; padding: 0.6rem 0.9rem;
    font-size: 0.85rem; cursor: pointer;
  }
  .stats-match-card:hover { border-color: var(--accent); }
  .stats-match-meta { color: var(--muted); font-size: 0.75rem; margin-bottom: 0.3rem; }
  .stats-match-meta.legs { margin-top: 0.2rem; margin-bottom: 0; }
  .stats-match-players { font-weight: 600; }
  .stats-match-detail.open { margin-top: 0.5rem; }
  .players-table.detail { margin-top: 0.5rem; }
  .leaderboard-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-top: 0.5rem; }
  .lb-label { font-size: 0.8rem; color: var(--muted); margin-bottom: 0.4rem; }
</style>
