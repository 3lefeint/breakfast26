<script>
  import { t } from '../../lib/i18n.js';
  // The route quiz: a score is shown and the player taps the first field of a route that finishes it
  // on the board, without throwing. The answer is the standard route, another valid route, or not a
  // valid first dart. Works on a phone, no darts needed.
  import { onMount } from 'svelte';
  import PageHeader from '../../lib/components/PageHeader.svelte';
  import DartBoard from '../../lib/components/DartBoard.svelte';
  import RouteChips from '../../lib/components/RouteChips.svelte';
  import { RANGES, rangeLabel, randomScore, judgeFirstDart, fieldName } from '../../lib/checkoutTraining.js';

  let rangeId = $state('all');
  let range = $derived(RANGES.find((r) => r.id === rangeId));
  let score = $state(null);
  let answer = $state(null);       // { field, verdict, route } once a dart was tapped
  let tally = $state({ standard: 0, valid: 0, invalid: 0 });
  let total = $derived(tally.standard + tally.valid + tally.invalid);

  const VERDICTS = {
    standard: t('The standard route'),
    valid: t('Valid, another route'),
    invalid: t('Not a valid first dart'),
  };

  async function next() {
    answer = null;
    score = await randomScore(range.low, range.high, score);
  }

  async function pick(id) {
    rangeId = id;
    tally = { standard: 0, valid: 0, invalid: 0 };
    await next();
  }

  async function choose(field) {
    if (answer || score == null) return;
    const res = await judgeFirstDart(score, field);
    if (res.error) return;
    answer = { field, ...res };
    tally[res.verdict] += 1;
  }

  onMount(next);
</script>

<PageHeader title={t('Route quiz')} subtitle={t('Tap the first dart of a route that finishes the score')} back="#checkout-trainer" />

<div class="chips" role="radiogroup" aria-label={t('Scores')}>
  {#each RANGES as r (r.id)}
    <button type="button" class="chip" class:active={rangeId === r.id} onclick={() => pick(r.id)}>{rangeLabel(r.low, r.high)}</button>
  {/each}
  <span class="tally">{t('{good} of {total} right', { good: tally.standard + tally.valid, total })}</span>
</div>

<div class="quiz">
  <div class="left">
    <div class="score">{score ?? '…'}</div>
    {#if answer}
      <div class="verdict {answer.verdict}">
        <div class="headline">{VERDICTS[answer.verdict]}</div>
        <div class="line">{t('You tapped')} <strong>{fieldName(answer.field)}</strong></div>
        {#if answer.route}<div class="line">{t('Standard route')}: <RouteChips route={answer.route} /></div>{/if}
      </div>
      <button class="btn" onclick={next}>{t('Next score')}</button>
    {:else}
      <div class="hint">{t('Which dart would you throw first?')}</div>
    {/if}
  </div>
  <div class="board">
    <DartBoard onSelect={choose} disabled={!!answer || score == null} />
  </div>
</div>

<style>
  .chips { display: flex; gap: 0.4rem; margin-bottom: 1.25rem; flex-wrap: wrap; align-items: center; }
  .chip { background: var(--glass); border: 1px solid var(--glass-border); color: var(--muted); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2); border-radius: 20px; padding: 0.35rem 1rem; font-family: inherit; font-size: 0.85rem; cursor: pointer; }
  .chip:hover { border-color: var(--accent); color: var(--text); }
  .chip.active { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); font-weight: 700; }
  .tally { margin-left: auto; color: var(--muted); font-size: 0.85rem; }
  .quiz { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr); gap: 1.5rem; align-items: start; }
  .left { display: flex; flex-direction: column; gap: 1.2rem; background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); border-radius: 16px; padding: 1.5rem; }
  .score { font-size: clamp(4rem, 12vw, 8rem); font-weight: 900; line-height: 1; color: var(--accent); }
  .hint { color: var(--muted); }
  .verdict { display: flex; flex-direction: column; gap: 0.5rem; padding: 0.9rem 1rem; border-radius: 12px; border: 1px solid var(--glass-border); background: rgba(0, 0, 0, 0.18); }
  .verdict.standard { border-color: var(--green); }
  .verdict.valid { border-color: var(--accent); }
  .verdict.invalid { border-color: var(--red); }
  .headline { font-weight: 800; font-size: 1.15rem; }
  .standard .headline { color: var(--green); }
  .valid .headline { color: var(--accent); }
  .invalid .headline { color: var(--red); }
  .line { color: var(--muted); display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
  .line strong { color: var(--text); }
  .btn { align-self: flex-start; border: none; border-radius: 8px; padding: 0.65rem 1.5rem; font-size: 0.95rem; font-weight: 600; cursor: pointer; background: #166534; color: #fff; }
  .board { display: flex; justify-content: center; --board-max: min(70vh, 100%); }
  @media (max-width: 760px) { .quiz { grid-template-columns: 1fr; } }
</style>
