<script>
  // Target Battle per player: how they throw (points per round, how many darts land on the target,
  // perfect turns, best turn) and, for the player picked, how often they hit each target number.
  import { cap } from '../../../lib/util.js';

  let { players = [] } = $props();

  let rows = $derived(players.filter((p) => p.turns > 0));
  let picked = $state(null);
  let current = $derived(rows.find((p) => p.player === picked) || rows[0] || null);
  let byTarget = $derived.by(() => {
    const map = new Map((current?.by_target || []).map((b) => [b.target, b]));
    return Array.from({ length: 20 }, (_, i) => map.get(i + 1) || { target: i + 1, darts: 0, hits: 0 });
  });

  function pct(b) { return b.darts ? (b.hits / b.darts) * 100 : 0; }
  function num(v, digits = 1) { return v == null ? '—' : v.toFixed(digits); }
</script>

{#if !rows.length}
  <div class="empty">No finished Target Battle games yet.</div>
{:else}
  <table class="players-table">
    <thead>
      <tr>
        <th>Player</th><th class="num">Rounds</th><th class="num">Points / round</th><th class="num">On target</th>
        <th class="num">Perfect turns</th><th class="num">Best turn</th><th class="num">Alone</th>
      </tr>
    </thead>
    <tbody>
      {#each rows as p (p.player)}
        <tr class:picked={current && p.player === current.player}>
          <td><button type="button" class="name" onclick={() => (picked = p.player)}>{cap(p.player)}</button></td>
          <td class="num">{p.turns}</td>
          <td class="num">{num(p.avg_points_per_round, 2)}</td>
          <td class="num" title="{p.hits} of {p.darts} darts">{p.hit_pct != null ? p.hit_pct.toFixed(0) + '%' : '—'}</td>
          <td class="num">{p.perfect_turns}</td>
          <td class="num">{p.best_turn?.score ?? '—'}</td>
          <td class="num">{p.solo_games}</td>
        </tr>
      {/each}
    </tbody>
  </table>

  {#if current}
    <div class="sub">{cap(current.player)} · darts on the target, by target number</div>
    <div class="bars" role="img" aria-label="Share of darts on the target for each target number from 1 to 20">
      {#each byTarget as b (b.target)}
        <div class="col" title={b.darts ? `${b.target}: ${b.hits} of ${b.darts} darts (${pct(b).toFixed(0)}%)` : `${b.target}: not a target yet`}>
          <div class="track"><div class="bar" class:few={b.darts > 0 && b.darts < 6} style:height="{pct(b)}%"></div></div>
          <div class="label">{b.target}</div>
        </div>
      {/each}
    </div>
    <div class="note">Lighter bars rest on fewer than six darts.</div>
  {/if}
{/if}

<style>
  .empty { color: var(--muted); text-align: center; padding: 1.5rem 0; }
  .players-table { width: 100%; border-collapse: collapse; }
  .players-table th { font-size: 0.75rem; color: var(--muted); font-weight: 500; text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid var(--border); }
  .players-table td { padding: 0.55rem 0.6rem; border-bottom: 1px solid var(--border); font-size: 0.85rem; }
  .num { text-align: right; }
  .players-table th.num { text-align: right; }
  .name { background: none; border: none; color: var(--text); font: inherit; cursor: pointer; padding: 0; }
  .name:hover { color: var(--accent); }
  tr.picked .name { color: var(--accent); font-weight: 700; }
  .sub { font-size: 0.75rem; color: var(--muted); margin: 1.25rem 0 0.5rem; }
  .bars { display: grid; grid-template-columns: repeat(20, 1fr); gap: 0.25rem; align-items: end; }
  .col { display: flex; flex-direction: column; align-items: center; gap: 0.25rem; }
  .track { width: 100%; height: 110px; display: flex; align-items: flex-end; background: color-mix(in srgb, var(--surface) 70%, var(--bg)); border-radius: 4px; }
  .bar { width: 100%; background: var(--accent); border-radius: 4px 4px 0 0; min-height: 0; }
  .bar.few { opacity: 0.45; }
  .label { font-size: 0.65rem; color: var(--muted); }
  .note { font-size: 0.7rem; color: var(--muted); margin-top: 0.4rem; }
</style>
