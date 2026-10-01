<script>
  // One row per player: their last finished games as small squares, oldest to
  // newest, coloured by the place they finished, plus their win streak.
  import { cap } from '../../../lib/util.js';
  import { RANKS, rankForPlace } from './ranks.js';

  let { players = [] } = $props();

  let rows = $derived(players.filter((p) => p.form?.games.length));
  let hasLower = $derived(rows.some((p) => p.form.games.some((g) => g.placement > 3)));

  function ordinal(n) {
    const mod100 = n % 100;
    const suffix = mod100 >= 11 && mod100 <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th');
    return n + suffix;
  }
  function describe(g) {
    const date = new Date(g.date).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
    return `${date} · ${ordinal(g.placement)} of ${g.size} · vs ${g.opponents.map(cap).join(', ')}`;
  }
</script>

{#if rows.length}
  <div class="legend">
    {#each RANKS.filter((r) => r.key !== 'other' || hasLower) as r}
      <span class="legend-item"><span class="swatch" style:background={r.color}></span>{r.label}</span>
    {/each}
    <span class="legend-item">oldest → newest</span>
  </div>
  {#each rows as p (p.player)}
    <div class="row" role="img"
         aria-label="{cap(p.player)}, last {p.form.games.length} games: {p.form.games.map((g) => ordinal(g.placement)).join(', ')}">
      <div class="name">{cap(p.player)}</div>
      <div class="squares">
        {#each p.form.games as g (g.match_id)}
          {@const rank = rankForPlace(g.placement)}
          <span class="square" style:background={rank.color} style:color={rank.ink} title={describe(g)}>{g.placement}</span>
        {/each}
      </div>
      <div class="streak">
        <span class:hot={p.form.current_streak >= 2}>Streak {p.form.current_streak}</span>
        <span class="best">best {p.form.best_streak}</span>
      </div>
    </div>
  {/each}
{/if}

<style>
  .legend { display: flex; flex-wrap: wrap; gap: 1rem; font-size: 0.75rem; color: var(--muted); margin-bottom: 0.6rem; }
  .legend-item { display: inline-flex; align-items: center; gap: 0.35rem; }
  .swatch { width: 0.8rem; height: 0.8rem; border-radius: 3px; display: inline-block; }
  .row { display: grid; grid-template-columns: 7rem 1fr 9rem; align-items: center; gap: 0.9rem; padding: 0.35rem 0; }
  .name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .squares { display: flex; flex-wrap: wrap; gap: 2px; }
  .square {
    display: inline-flex; align-items: center; justify-content: center;
    width: 1.35rem; height: 1.35rem; border-radius: 4px;
    font-size: 0.65rem; font-weight: 700; font-variant-numeric: tabular-nums;
  }
  .streak { text-align: right; font-size: 0.85rem; font-variant-numeric: tabular-nums; }
  .streak .hot { color: var(--green); font-weight: 700; }
  .streak .best { color: var(--muted); margin-left: 0.5rem; font-size: 0.8rem; }
  @media (max-width: 600px) {
    .row { grid-template-columns: 5rem 1fr; }
    .streak { grid-column: 1 / -1; text-align: left; }
  }
</style>
