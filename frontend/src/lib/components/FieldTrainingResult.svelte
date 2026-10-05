<script>
  // The result of a finished Field Training run: the points, the hit rate and the share of singles,
  // doubles and triples, the rating and the personal best of a run that counts, the points of every
  // turn and where the darts landed. Shown on Home and on the TV.
  import { fieldLabel, RATING_LABELS, percent, runDots } from '../fieldTraining.js';
  import DartBoard from './DartBoard.svelte';

  let { ft, large = false } = $props();

  let r = $derived(ft.result || {});
  let isBull = $derived(ft.field === 25);
  let hits = $derived(ft.hits || {});
  let hitCount = $derived((hits.singles || 0) + (hits.doubles || 0) + (hits.triples || 0));
  let maxTurn = $derived(Math.max(1, ...(ft.turn_points || [0])));
  let mark = $derived(r.personal_best ? 'Personal best' : null);
</script>

<div class="result" class:large>
  <div class="headline">
    <div class="points">{r.points}<span class="unit">points</span></div>
    <div class="meta">
      {ft.player} · {fieldLabel(ft.field)} · {r.darts} of {ft.darts} darts
    </div>
    <div class="badges">
      {#if r.counts && r.rating}<span class="badge rating {r.rating}">{RATING_LABELS[r.rating]}</span>{/if}
      {#if mark}<span class="badge best">{mark}</span>{/if}
      {#if !r.counts}<span class="badge practice">Practice</span>{/if}
    </div>
    {#if r.counts && !r.personal_best && r.previous_best != null}
      <div class="meta">Best so far {r.previous_best} points per {ft.standard_darts} darts, this run {r.scaled_points}</div>
    {/if}
  </div>

  <div class="content">
    <div class="stats">
      <div class="stat"><span class="value">{percent(r.hit_rate)}</span><span class="label">Hit rate</span></div>
      <div class="stat"><span class="value">{hitCount}</span><span class="label">Hits</span></div>
      <div class="stat"><span class="value">{hits.singles || 0}</span><span class="label">{isBull ? 'Outer bull' : 'Singles'}</span></div>
      <div class="stat"><span class="value">{hits.doubles || 0}</span><span class="label">{isBull ? "Bull's eye" : 'Doubles'}</span></div>
      {#if !isBull}<div class="stat"><span class="value">{hits.triples || 0}</span><span class="label">Triples</span></div>{/if}
    </div>

    <div class="turns-box">
      <div class="turns" aria-label="Points of every turn">
        {#each ft.turn_points || [] as p, i}
          <span class="bar" title="Turn {i + 1}: {p}" style="height: {Math.max(4, (p / maxTurn) * 100)}%"></span>
        {/each}
      </div>
      <div class="caption">Points per turn</div>
    </div>

    <div class="board">
      <DartBoard readonly darts={runDots(ft)} />
    </div>
  </div>
</div>

<style>
  .result { display: flex; flex-direction: column; gap: 1.2rem; }
  .headline { display: flex; flex-direction: column; gap: 0.4rem; }
  .points { font-size: 3rem; font-weight: 900; color: var(--accent); line-height: 1; }
  .unit { font-size: 1rem; color: var(--muted); font-weight: 600; margin-left: 0.5rem; }
  .meta { color: var(--muted); font-size: 0.9rem; }
  .badges { display: flex; gap: 0.5rem; flex-wrap: wrap; }
  .badge { border-radius: 999px; padding: 0.15rem 0.8rem; font-size: 0.8rem; font-weight: 700; border: 1px solid var(--border); color: var(--muted); }
  .badge.rating { color: var(--accent); border-color: var(--accent); }
  .badge.best { color: var(--green); border-color: var(--green); }
  .content { display: grid; grid-template-columns: 1fr minmax(0, 18rem); gap: 1.2rem; align-items: start; }
  .stats { grid-column: 1; display: flex; flex-wrap: wrap; gap: 0.6rem; }
  .stat { display: flex; flex-direction: column; min-width: 5.5rem; padding: 0.6rem 0.9rem; background: var(--bg); border: 1px solid var(--border); border-radius: 10px; }
  .value { font-size: 1.4rem; font-weight: 800; white-space: nowrap; }
  .label { font-size: 0.7rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
  .turns-box { grid-column: 1; }
  .caption { margin-top: 0.3rem; font-size: 0.7rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
  .turns { display: flex; align-items: flex-end; gap: 2px; height: 5rem; padding: 0.4rem; background: var(--bg); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
  .bar { flex: 1; min-width: 2px; background: var(--accent); border-radius: 2px 2px 0 0; opacity: 0.85; }
  .board { grid-column: 2; grid-row: 1 / span 2; }
  .large .points { font-size: clamp(3rem, 8vw, 7rem); }
  .large .meta { font-size: clamp(0.9rem, 1.6vw, 1.5rem); }
  .large .content { grid-template-columns: 1fr minmax(0, min(36vw, 50vh)); }
  .large .value { font-size: clamp(1.4rem, 3vw, 2.8rem); }
  .large .stat { padding: 0.8rem 1.2rem; }
  .large .turns { height: 9rem; }
  @media (max-width: 640px) {
    .content { grid-template-columns: 1fr; }
    .board, .stats, .turns-box { grid-column: 1; grid-row: auto; }
  }
</style>
