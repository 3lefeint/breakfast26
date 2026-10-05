<script>
  // The result of a finished Black Belt run: the belt or how far the player got, the restarts and
  // darts, how far each attempt got and where the darts landed. Shown on Home and on the TV.
  import BlackBeltLadder from './BlackBeltLadder.svelte';
  import DartBoard from './DartBoard.svelte';
  import { runDots, stepLabel } from '../blackBelt.js';

  let { bb, large = false } = $props();

  let r = $derived(bb.result || {});
  let attempts = $derived(r.attempts || []);
  let total = $derived(bb.steps.length);
  let reached = $derived(r.furthest > 0 ? stepLabel(bb.steps[r.furthest - 1]) : '—');
</script>

<div class="result" class:large>
  <div class="headline">
    {#if r.belt}
      <div class="belt">🥋 Black Belt</div>
      <div class="meta">{bb.player} · {r.darts} darts · {r.restarts} {r.restarts === 1 ? 'restart' : 'restarts'}{bb.backwards ? ' · backwards' : ''}</div>
    {:else}
      <div class="points">{r.furthest}<span class="unit">of {total} fields</span></div>
      <div class="meta">{bb.player} · furthest {reached} · {r.darts} darts · {r.restarts} {r.restarts === 1 ? 'restart' : 'restarts'}{bb.backwards ? ' · backwards' : ''}</div>
    {/if}
  </div>

  <div class="content">
    <div class="left">
      <BlackBeltLadder steps={bb.steps} position={r.furthest} belt={r.belt} />
      <div class="attempts" aria-label="Fields done in every attempt">
        {#each attempts as a, i}
          <span class="bar" class:full={a >= total} title="Attempt {i + 1}: {a} of {total}" style="height: {Math.max(4, (a / total) * 100)}%"></span>
        {/each}
      </div>
      <div class="caption">Fields done per attempt</div>
    </div>
    <div class="board"><DartBoard readonly darts={runDots(bb)} /></div>
  </div>
</div>

<style>
  .result { display: flex; flex-direction: column; gap: 1.2rem; }
  .headline { display: flex; flex-direction: column; gap: 0.4rem; }
  .belt { font-size: 2.6rem; font-weight: 900; color: var(--green); line-height: 1.1; }
  .points { font-size: 3rem; font-weight: 900; color: var(--accent); line-height: 1; }
  .unit { font-size: 1rem; color: var(--muted); font-weight: 600; margin-left: 0.5rem; }
  .meta { color: var(--muted); font-size: 0.9rem; }
  .content { display: grid; grid-template-columns: 1fr minmax(0, 18rem); gap: 1.2rem; align-items: start; }
  .left { display: flex; flex-direction: column; gap: 1rem; }
  .attempts { display: flex; align-items: flex-end; gap: 3px; height: 5rem; padding: 0.4rem; background: var(--bg); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
  .bar { flex: 1; min-width: 3px; max-width: 2.5rem; background: var(--accent); border-radius: 2px 2px 0 0; opacity: 0.85; }
  .bar.full { background: var(--green); }
  .caption { font-size: 0.7rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; margin-top: -0.6rem; }
  .large .belt { font-size: clamp(3rem, 8vw, 7rem); }
  .large .points { font-size: clamp(3rem, 8vw, 7rem); }
  .large .meta { font-size: clamp(0.9rem, 1.6vw, 1.5rem); }
  .large .content { grid-template-columns: 1fr minmax(0, min(36vw, 50vh)); }
  .large .attempts { height: 9rem; }
  .large .left { font-size: clamp(0.9rem, 1.5vw, 1.4rem); }
  @media (max-width: 640px) { .content { grid-template-columns: 1fr; } }
</style>
