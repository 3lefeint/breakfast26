<script>
  // Target Battle half of the Stats tab. The chips pick the scoring profile, since points are only
  // comparable under the same rules; everything below counts only games of that profile.
  import { cap } from '../../../lib/util.js';
  import { SCORING_SHORT } from '../../../lib/targetBattle.js';
  import RecentMatches from './RecentMatches.svelte';
  import PlacementRows from './PlacementRows.svelte';
  import FormStrip from './FormStrip.svelte';
  import HeadToHead from './HeadToHead.svelte';
  import TargetBattlePlayers from './TargetBattlePlayers.svelte';

  function remembered() {
    try {
      const saved = localStorage.getItem('statsTargetBattleScoring');
      return saved in SCORING_SHORT ? saved : 'standard';
    } catch (e) {
      return 'standard';
    }
  }

  let scoring = $state(remembered());
  let data = $state(null);
  let loadFailed = $state(false);

  function select(key) {
    scoring = key;
    try { localStorage.setItem('statsTargetBattleScoring', key); } catch (e) { /* remembering is optional */ }
  }

  $effect(() => {
    const wanted = scoring;
    data = null;
    loadFailed = false;
    fetch(`/api/stats/target-battle/overview?scoring=${wanted}`)
      .then((r) => r.json())
      .then((body) => { if (wanted === scoring) data = body; })
      .catch(() => { if (wanted === scoring) loadFailed = true; });
  });

  let summary = $derived(data?.summary || {});
  let records = $derived(data?.records || {});
  let competitors = $derived((data?.players || []).filter((p) => p.games > 0));

  function duration(minutes) {
    if (minutes == null) return '—';
    return minutes < 60 ? `${minutes.toFixed(1)} min` : `${(minutes / 60).toFixed(1)} h`;
  }
  function dateOf(d) { return new Date(d).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }); }
</script>

<div class="profiles" role="tablist" aria-label="Scoring profile">
  {#each Object.entries(SCORING_SHORT) as [key, label]}
    <button type="button" role="tab" class="profile" class:active={scoring === key} aria-selected={scoring === key}
            onclick={() => select(key)}>{label}</button>
  {/each}
</div>

{#if loadFailed}
  <div class="empty">Could not load stats.</div>
{:else if data}
  <div class="section-title">Overview</div>
  <div class="stat-tiles">
    <div class="stat-tile"><div class="stat-tile-label">Games</div><div class="stat-tile-value">{summary.games ?? 0}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">Total playtime</div><div class="stat-tile-value">{duration(summary.total_minutes)}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">Average game</div><div class="stat-tile-value">{duration(summary.avg_minutes)}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">Longest game</div><div class="stat-tile-value">{duration(summary.longest_minutes)}</div></div>
  </div>
  <div class="records">
    <div class="record">
      <div class="stat-tile-label">Best game</div>
      <div class="stat-tile-value">{records.best_game?.score ?? '—'}</div>
      <div class="record-sub">
        {#if records.best_game}{records.best_game.rounds} {records.best_game.rounds === 1 ? 'round' : 'rounds'} · {cap(records.best_game.player)} · {dateOf(records.best_game.date)}{/if}
      </div>
    </div>
    <div class="record">
      <div class="stat-tile-label">Best turn</div>
      <div class="stat-tile-value">{records.best_turn?.score ?? '—'}</div>
      <div class="record-sub">
        {#if records.best_turn}{cap(records.best_turn.player)} · {dateOf(records.best_turn.date)}{/if}
      </div>
    </div>
  </div>

  <div class="section-title top">Wins and placements</div>
  <PlacementRows players={competitors} emptyText="No Target Battle games against others yet." />

  <div class="section-title top">Form · last 15 games</div>
  <FormStrip players={competitors} />

  <div class="section-title top">Head to head</div>
  <HeadToHead pairs={data.head_to_head} order={competitors.map((p) => p.player)} />

  <div class="section-title top">Players</div>
  <TargetBattlePlayers players={data.players} />
{/if}

<RecentMatches mode="target_battle" />

<style>
  .profiles { display: flex; gap: 0.4rem; margin-bottom: 1.25rem; flex-wrap: wrap; }
  .profile {
    background: var(--bg); border: 1px solid var(--border); color: var(--muted);
    border-radius: 20px; padding: 0.3rem 0.9rem; font-family: inherit; font-size: 0.8rem; cursor: pointer;
  }
  .profile:hover { border-color: var(--accent); color: var(--text); }
  .profile.active { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); font-weight: 700; }
  .section-title { font-size: 0.8rem; color: var(--muted); margin: 0 0 0.6rem; letter-spacing: 0.06em; text-transform: uppercase; }
  .section-title.top { margin-top: 1.75rem; }
  .empty { color: var(--muted); text-align: center; padding: 1.5rem 0; }
  .stat-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 0.75rem; }
  .stat-tile { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 0.75rem 0.9rem; text-align: center; }
  .records { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; margin-top: 0.75rem; }
  .record { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 0.75rem 0.9rem; text-align: center; }
  .record-sub { font-size: 0.75rem; color: var(--muted); margin-top: 0.2rem; min-height: 1.1em; }
  @media (max-width: 600px) { .records { grid-template-columns: 1fr; } }
  .stat-tile-label { font-size: 0.7rem; color: var(--muted); margin-bottom: 0.3rem; }
  .stat-tile-value { font-size: 1.4rem; font-weight: 600; }
</style>
