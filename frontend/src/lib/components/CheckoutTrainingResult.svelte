<script>
  import { t } from '../i18n.js';
  // The result of a finished Checkout Training run: how many attempts worked, and every attempt
  // with its score and the standard route, so the ones that did not work show what to practise.
  // Shown on Home and on the TV.
  import { rangeLabel, percent, fieldName } from '../checkoutTraining.js';
  import RouteChips from './RouteChips.svelte';

  let { co, large = false } = $props();

  let r = $derived(co.result || {});
  let results = $derived(co.results || []);
</script>

<div class="result" class:large>
  <div class="headline">
    <div class="rate">{r.successes}<span class="of">&nbsp;/&nbsp;{r.attempts}</span><span class="pct">{percent(r.rate)}</span></div>
    <div class="meta">
      {co.player} · {rangeLabel(co.low, co.high)} · {t('{n} attempts', { n: r.attempts })}
      {#if !r.completed}· <span class="badge">{t('Ended early')}</span>{/if}
    </div>
  </div>

  <div class="attempts">
    {#each results as a, i}
      <div class="row" class:miss={!a.success}>
        <span class="no">{i + 1}</span>
        <span class="mark">{a.success ? '✓' : '✗'}</span>
        <span class="score">{a.score}</span>
        <span class="darts">{a.success ? t('{n} darts', { n: a.darts }) : (a.fields || []).map(fieldName).join(' ')}</span>
        <span class="route"><RouteChips route={a.route} /></span>
      </div>
    {/each}
  </div>
</div>

<style>
  .result { display: flex; flex-direction: column; gap: 1.2rem; }
  .headline { display: flex; flex-direction: column; gap: 0.4rem; }
  .rate { font-size: 3rem; font-weight: 900; color: var(--accent); line-height: 1; }
  .of { font-size: 1.6rem; color: var(--muted); font-weight: 700; }
  .pct { font-size: 1rem; color: var(--muted); font-weight: 600; margin-left: 0.8rem; }
  .meta { color: var(--muted); font-size: 0.9rem; }
  .badge { border: 1px solid var(--glass-border); border-radius: 999px; padding: 0.1rem 0.7rem; font-size: 0.8rem; font-weight: 700; }
  .attempts { display: flex; flex-direction: column; gap: 0.35rem; max-height: 22rem; overflow-y: auto; }
  .row { display: grid; grid-template-columns: 2rem 1.6rem 3.2rem 8rem 1fr; gap: 0.6rem; align-items: center; padding: 0.4rem 0.7rem; background: var(--glass); border: 1px solid var(--glass-border); border-radius: 10px; }
  .row.miss { border-color: color-mix(in srgb, var(--red) 55%, transparent); }
  .no { color: var(--muted); font-size: 0.8rem; }
  .mark { font-weight: 900; color: var(--green); }
  .miss .mark { color: var(--red); }
  .score { font-weight: 900; font-size: 1.1rem; }
  .darts { color: var(--muted); font-size: 0.85rem; }
  .large .rate { font-size: clamp(3rem, 8vw, 7rem); }
  .large .of { font-size: clamp(1.6rem, 4vw, 3.4rem); }
  .large .meta { font-size: clamp(0.9rem, 1.6vw, 1.5rem); }
  .large .attempts { max-height: 38vh; }
  .large .row { font-size: clamp(0.9rem, 1.5vw, 1.4rem); }
</style>
