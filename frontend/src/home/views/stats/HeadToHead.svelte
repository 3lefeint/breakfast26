<script>
  // Players against each other: a cell is the share of their shared games in
  // which the row player finished ahead of the column player. Green = the row
  // player leads, red = trails, neutral = even; every cell also carries the
  // numbers, so the colour is never the only signal.
  import { cap } from '../../../lib/util.js';

  let { pairs = [], order = [] } = $props();

  let names = $derived.by(() => {
    const inPairs = new Set(pairs.flatMap((p) => [p.a, p.b]));
    return [...order.filter((n) => inPairs.has(n)), ...[...inPairs].filter((n) => !order.includes(n)).sort()];
  });

  let cells = $derived.by(() => {
    const map = new Map();
    for (const p of pairs) {
      map.set(`${p.a}|${p.b}`, { ahead: p.a_ahead, games: p.games });
      map.set(`${p.b}|${p.a}`, { ahead: p.b_ahead, games: p.games });
    }
    return map;
  });

  function look(cell) {
    if (!cell) return null;
    const share = cell.ahead / cell.games;
    const strength = Math.round(Math.abs(share - 0.5) * 2 * 60);
    const hue = share > 0.5 ? 'var(--accent)' : 'var(--red)';
    return {
      percent: Math.round(share * 100),
      background: strength ? `color-mix(in srgb, ${hue} ${strength}%, var(--surface))` : 'var(--surface)',
    };
  }
</script>

{#if !pairs.length}
  <div class="empty">No games with two or more players yet.</div>
{:else}
  <div class="legend">
    <span class="legend-item"><span class="swatch" style:background="color-mix(in srgb, var(--accent) 45%, var(--surface))"></span>row player ahead more often</span>
    <span class="legend-item"><span class="swatch" style:background="color-mix(in srgb, var(--red) 45%, var(--surface))"></span>behind more often</span>
    <span class="legend-item"><span class="swatch" style:background="var(--surface)"></span>even</span>
  </div>
  <div class="note">Share of shared games in which the row player finished ahead of the column player.</div>

  <div class="matrix" style:--n={names.length} style:max-width="calc(5.5rem + {names.length} * 4.4rem)"
       role="table" aria-label="Head to head: how often the row player finished ahead of the column player">
    <div class="corner"></div>
    {#each names as col}
      <div class="col-head" title={cap(col)}>{cap(col)}</div>
    {/each}
    {#each names as row}
      <div class="row-head" title={cap(row)}>{cap(row)}</div>
      {#each names as col}
        {#if row === col}
          <div class="cell self"></div>
        {:else}
          {@const cell = cells.get(`${row}|${col}`)}
          {@const l = look(cell)}
          {#if l}
            <div class="cell" style:background={l.background}
                 title="{cap(row)} finished ahead of {cap(col)} in {cell.ahead} of {cell.games} games ({l.percent}%)">
              <span class="pct">{l.percent}%</span>
              <span class="count">{cell.ahead}/{cell.games}</span>
            </div>
          {:else}
            <div class="cell none" title="{cap(row)} and {cap(col)} have not played together">·</div>
          {/if}
        {/if}
      {/each}
    {/each}
  </div>
{/if}

<style>
  .empty { color: var(--muted); text-align: center; padding: 1.5rem 0; }
  .legend { display: flex; flex-wrap: wrap; gap: 1rem; font-size: 0.75rem; color: var(--muted); margin-bottom: 0.3rem; }
  .legend-item { display: inline-flex; align-items: center; gap: 0.35rem; }
  .swatch { width: 0.8rem; height: 0.8rem; border-radius: 3px; display: inline-block; border: 1px solid var(--border); }
  .note { font-size: 0.75rem; color: var(--muted); margin-bottom: 0.6rem; }
  .matrix {
    display: grid; grid-template-columns: 5.5rem repeat(var(--n), minmax(0, 1fr)); gap: 2px;
  }
  .col-head, .row-head {
    font-size: 0.7rem; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .col-head { text-align: center; padding-bottom: 0.2rem; align-self: end; }
  .row-head { align-self: center; padding-right: 0.4rem; text-align: right; }
  .cell {
    border: 1px solid var(--border); border-radius: 4px; min-height: 2.4rem;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    font-variant-numeric: tabular-nums; line-height: 1.15;
  }
  .pct { font-size: 0.8rem; font-weight: 700; }
  .count { font-size: 0.62rem; color: var(--muted); }
  .cell.self { background: transparent; border-color: transparent; }
  .cell.none { color: var(--muted); }
</style>
