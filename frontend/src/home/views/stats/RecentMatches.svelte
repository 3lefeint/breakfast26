<script>
  // Collapsible list of recent matches for one game mode, each expandable to
  // its per-player detail.
  import { onMount } from 'svelte';
  import { cap } from '../../../lib/util.js';
  import { SCORING_SHORT } from '../../../lib/targetBattle.js';
  import { fieldLabel, RATING_LABELS, percent } from '../../../lib/fieldTraining.js';

  let { mode } = $props();

  let matches = $state([]);
  let open = $state(false);
  let openMatches = $state(new Set());
  let matchDetails = $state({});

  onMount(async () => {
    try {
      matches = await fetch(`/api/stats/matches?mode=${mode}`).then((r) => r.json());
    } catch (e) {
      matches = [];
    }
  });

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
  function matchMode(m) {
    if (m.game_mode === 'Target Battle') {
      return `Target Battle · ${m.points_start} ${m.points_start === 1 ? 'round' : 'rounds'} · ${SCORING_SHORT[m.scoring] || m.scoring}`;
    }
    if (m.game_mode === 'Killer') return 'Killer';
    if (m.game_mode === 'Black Belt') return `Black Belt · ${m.backwards ? 'D20 down to D1' : 'D1 up to D20'}`;
    if (m.game_mode === 'Field Training') {
      return `Field Training · ${m.field != null ? fieldLabel(m.field) : '?'} · ${m.points_start} darts`;
    }
    return [m.game_mode, m.points_start ? m.points_start + ' pts' : ''].filter(Boolean).join(' ');
  }
  function matchPlayers(m) { return (m.players || []).map(cap).join(' · '); }
  function legsLine(m) {
    const lw = m.legs_won || {};
    const lt = m.legs_total || 0;
    const parts = Object.entries(lw).map(([n, c]) => `${cap(n)} ${c}`).join(' · ');
    const suffix = lt > 0 ? `  (${lt} leg${lt !== 1 ? 's' : ''})` : '';
    return parts ? parts + suffix : '';
  }
</script>

<button type="button" class="section-title collapsible-title" onclick={() => open = !open}>
  <span class="chevron" class:open>▸</span> Recent matches
</button>
{#if open}
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
            {:else if mode === 'target_battle'}
              <table class="players-table stats-table detail">
                <thead><tr><th>Player</th><th class="num-cell">Place</th><th class="num-cell">Points</th></tr></thead>
                <tbody>
                  {#each matchDetails[m.match_id].players as p}
                    <tr>
                      <td>{cap(p.player)}</td>
                      <td class="num-cell">{ordinal(p.placement)}</td>
                      <td class="num-cell">{p.score}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
              <table class="players-table stats-table detail">
                <thead>
                  <tr>
                    <th>Round</th><th class="num-cell">Target</th>
                    {#each matchDetails[m.match_id].players as p}<th class="num-cell">{cap(p.player)}</th>{/each}
                  </tr>
                </thead>
                <tbody>
                  {#each matchDetails[m.match_id].history as r}
                    <tr>
                      <td>{r.tiebreak ? `Tiebreak ${r.round}` : r.round}</td>
                      <td class="num-cell">{r.target}</td>
                      {#each matchDetails[m.match_id].players as p}<td class="num-cell">{r.scores[p.player] ?? '—'}</td>{/each}
                    </tr>
                  {/each}
                </tbody>
              </table>
            {:else if mode === 'black_belt'}
              <table class="players-table stats-table detail">
                <thead>
                  <tr>
                    <th>Player</th><th class="num-cell">Fields</th><th class="num-cell">Restarts</th>
                    <th class="num-cell">Darts</th><th class="num-cell"></th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>{cap(matchDetails[m.match_id].player)}</td>
                    <td class="num-cell">{matchDetails[m.match_id].furthest}</td>
                    <td class="num-cell">{matchDetails[m.match_id].restarts}</td>
                    <td class="num-cell">{matchDetails[m.match_id].darts}</td>
                    <td class="num-cell">{matchDetails[m.match_id].belt ? 'Belt' : ''}</td>
                  </tr>
                </tbody>
              </table>
            {:else if mode === 'field_training'}
              <table class="players-table stats-table detail">
                <thead>
                  <tr>
                    <th>Player</th><th class="num-cell">Darts</th><th class="num-cell">Points</th>
                    <th class="num-cell">Hit rate</th><th class="num-cell">Singles</th>
                    <th class="num-cell">Doubles</th><th class="num-cell">Triples</th><th class="num-cell"></th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>{cap(matchDetails[m.match_id].player)}</td>
                    <td class="num-cell">{matchDetails[m.match_id].darts}</td>
                    <td class="num-cell">{matchDetails[m.match_id].points}</td>
                    <td class="num-cell">{percent(matchDetails[m.match_id].hit_rate)}</td>
                    <td class="num-cell">{matchDetails[m.match_id].singles}</td>
                    <td class="num-cell">{matchDetails[m.match_id].doubles}</td>
                    <td class="num-cell">{matchDetails[m.match_id].triples}</td>
                    <td class="num-cell">{matchDetails[m.match_id].counts ? RATING_LABELS[matchDetails[m.match_id].rating] : 'Practice'}</td>
                  </tr>
                </tbody>
              </table>
            {:else if mode === 'killer'}
              <table class="players-table stats-table detail">
                <thead>
                  <tr>
                    <th>Player</th><th class="num-cell">Place</th><th class="num-cell">Number</th>
                    <th class="num-cell">Lives left</th><th class="num-cell">Killer on turn</th>
                    <th class="num-cell">Taken</th><th class="num-cell">Knockouts</th>
                    <th class="num-cell">Own goals</th>
                  </tr>
                </thead>
                <tbody>
                  {#each matchDetails[m.match_id].players as p}
                    <tr>
                      <td>{cap(p.player)}</td>
                      <td class="num-cell">{ordinal(p.placement)}</td>
                      <td class="num-cell">{p.number}</td>
                      <td class="num-cell">{p.lives_left ?? '—'}</td>
                      <td class="num-cell">{p.killer_turn ?? '—'}</td>
                      <td class="num-cell">{p.taken}</td>
                      <td class="num-cell">{p.knockouts}</td>
                      <td class="num-cell">{p.own_goals}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            {:else if mode === 'elimination'}
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
                <thead><tr><th>Player</th><th class="num-cell">Avg</th><th class="num-cell">180</th><th class="num-cell">CO%</th></tr></thead>
                <tbody>
                  {#each Object.entries(matchDetails[m.match_id]) as [name, s]}
                    <tr>
                      <td>{cap(name)}</td>
                      <td class="num-cell">{s.avg3 != null ? s.avg3.toFixed(1) : '—'}</td>
                      <td class="num-cell">{s.s180 ?? '—'}</td>
                      <td class="num-cell">{s.co_attempts ? s.co_pct + '%' : '—'}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            {/if}
          </div>
        {/if}
      </div>
    {/each}
  {/if}
</div>
{/if}

<style>
  .section-title { font-size: 0.8rem; color: var(--muted); margin: 1.5rem 0 0.5rem; letter-spacing: 0.06em; text-transform: uppercase; }
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
  .stats-empty { color: var(--muted); text-align: center; padding: 1.5rem 0; }
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
</style>
