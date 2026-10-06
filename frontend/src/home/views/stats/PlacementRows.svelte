<script>
  import { t } from '../../../lib/i18n.js';
  // One row per player: a stacked bar of how often they finished 1st, 2nd and
  // 3rd, with a marker at the win share they would have by chance (a win in a
  // two-player game is worth less than in a three-player game). Bar past the
  // marker = more wins than chance would give.
  import { cap } from '../../../lib/util.js';
  import { RANKS } from './ranks.js';

  let { players = [], emptyText = t('No Elimination games yet — play one first.') } = $props();

  let rows = $derived(players.map((p) => {
    const share = (n) => (p.games ? (n / p.games) * 100 : 0);
    return {
      ...p,
      segments: RANKS
        .map((r) => ({ ...r, n: p.placements[r.key], width: share(p.placements[r.key]) }))
        .filter((s) => s.n > 0),
      expectedShare: share(p.expected_wins),
      diff: p.wins - p.expected_wins,
    };
  }));
  let hasLower = $derived(players.some((p) => p.placements.other > 0));

  function signed(v) { return (v >= 0 ? '+' : '−') + Math.abs(v).toFixed(1); }
</script>

{#if !rows.length}
  <div class="empty">{emptyText}</div>
{:else}
  <div class="legend">
    {#each RANKS.filter((r) => r.key !== 'other' || hasLower) as r}
      <span class="legend-item"><span class="swatch" style:background={r.color}></span>{r.label}</span>
    {/each}
    <span class="legend-item"><span class="tick"></span>{t('expected by chance')}</span>
  </div>

  {#each rows as p (p.player)}
    <div class="row" role="img"
         aria-label={t('{name}: {wins} wins in {games} games, {expected} expected by chance', { name: cap(p.player), wins: p.wins, games: p.games, expected: p.expected_wins.toFixed(1) })}>
      <div class="name">{cap(p.player)}</div>
      <div class="bar-wrap">
        <div class="bar">
          {#each p.segments as s}
            <div class="segment" style:width="{s.width}%" style:background={s.color} style:color={s.ink}
                 title={t('{label}: {n} of {games} games ({pct}%)', { label: s.label, n: s.n, games: p.games, pct: s.width.toFixed(0) })}>{s.n}</div>
          {/each}
        </div>
        <div class="expected" style:left="{p.expectedShare}%"
             title={t('Expected by chance: {wins} wins ({pct}%)', { wins: p.expected_wins.toFixed(1), pct: p.expectedShare.toFixed(0) })}></div>
      </div>
      <div class="numbers">
        <span class="wins">{p.wins}/{p.games}</span> <span class="pct">{p.win_pct.toFixed(0)}%</span>
        <span class="diff" class:up={p.diff > 0.05} class:down={p.diff < -0.05}
              title={t('Wins minus the wins expected by chance')}>{signed(p.diff)}</span>
      </div>
    </div>
  {/each}
{/if}

<style>
  .empty { color: var(--muted); text-align: center; padding: 1.5rem 0; }
  .legend { display: flex; flex-wrap: wrap; gap: 1rem; font-size: 0.75rem; color: var(--muted); margin-bottom: 0.6rem; }
  .legend-item { display: inline-flex; align-items: center; gap: 0.35rem; }
  .swatch { width: 0.8rem; height: 0.8rem; border-radius: 3px; display: inline-block; }
  .tick { width: 2px; height: 0.95rem; background: var(--text); display: inline-block; }
  .row {
    display: grid; grid-template-columns: 7rem 1fr 9rem; align-items: center; gap: 0.9rem;
    padding: 0.45rem 0;
  }
  .name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .bar-wrap { position: relative; padding: 0.3rem 0; }
  .bar { display: flex; gap: 2px; height: 1.6rem; }
  .segment {
    display: flex; align-items: center; justify-content: center; min-width: 1.4rem;
    font-size: 0.75rem; font-weight: 700; font-variant-numeric: tabular-nums;
    border-radius: 0 4px 4px 0;
  }
  .segment:first-child { border-radius: 4px 4px 4px 4px; }
  .expected {
    position: absolute; top: 0; bottom: 0; width: 2px; background: var(--text);
    transform: translateX(-1px); pointer-events: auto;
  }
  .numbers { text-align: right; font-variant-numeric: tabular-nums; font-size: 0.85rem; }
  .wins { font-weight: 700; }
  .pct { color: var(--muted); margin-left: 0.3rem; }
  .diff { margin-left: 0.5rem; color: var(--muted); font-size: 0.8rem; }
  .diff.up { color: var(--green); }
  .diff.down { color: var(--red); }
  @media (max-width: 600px) {
    .row { grid-template-columns: 5rem 1fr; }
    .numbers { grid-column: 1 / -1; text-align: left; }
  }
</style>
