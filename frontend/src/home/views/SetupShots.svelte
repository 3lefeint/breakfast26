<script>
  import { t } from '../../lib/i18n.js';
  // Setup shots: from a score, tap where the first darts would land. After every dart the app says what
  // is left and what that rest allows: a finish with one, two or three darts, or none. No darts
  // needed, works on a phone.
  import { onMount } from 'svelte';
  import PageHeader from '../../lib/components/PageHeader.svelte';
  import DartBoard from '../../lib/components/DartBoard.svelte';
  import RouteChips from '../../lib/components/RouteChips.svelte';
  import { rangeLabel, randomScore, setupResult, fieldName } from '../../lib/checkoutTraining.js';

  // Scores that cannot be finished with one dart, the ones where a setup dart matters.
  const RANGES = [
    { id: 'mid', low: 41, high: 100 },
    { id: 'high', low: 101, high: 170 },
    { id: 'all', low: 41, high: 170 },
  ];

  let rangeId = $state('mid');
  let range = $derived(RANGES.find((r) => r.id === rangeId));
  let score = $state(null);
  let fields = $state([]);
  let info = $state(null);        // what the app says about the darts so far

  async function next() {
    fields = [];
    info = null;
    score = await randomScore(range.low, range.high, score);
  }

  async function pick(id) {
    rangeId = id;
    await next();
  }

  async function tap(field) {
    if (score == null || fields.length >= 3 || (info && info.state !== 'open')) return;
    const res = await setupResult(score, [...fields, field]);
    if (res.error) return;
    fields = [...fields, field];
    info = res;
  }

  async function undoDart() {
    if (!fields.length) return;
    fields = fields.slice(0, -1);
    info = fields.length ? await setupResult(score, fields) : null;
  }

  const dartsText = (n) => (n === 1 ? t('1 dart') : t('{n} darts', { n }));

  onMount(next);
</script>

<PageHeader title={t('Setup shots')} subtitle={t('Leave a rest you can finish')} back="#checkout-trainer" />

<div class="chips" role="radiogroup" aria-label={t('Scores')}>
  {#each RANGES as r (r.id)}
    <button type="button" class="chip" class:active={rangeId === r.id} onclick={() => pick(r.id)}>{rangeLabel(r.low, r.high)}</button>
  {/each}
</div>

<div class="shots">
  <div class="left">
    <div class="caption">{t('Score')}</div>
    <div class="score">{score ?? '…'}</div>

    <div class="darts">
      {#each [0, 1, 2] as i}
        <span class="dart" class:empty={fields[i] == null}>{fields[i] != null ? fieldName(fields[i]) : '—'}</span>
      {/each}
    </div>

    {#if !info}
      <div class="hint">{t('Tap the board where your first dart should land.')}</div>
    {:else if info.state === 'bust'}
      <div class="verdict bad"><div class="headline">{t('Bust')}</div><div class="line">{t('The score stays {score}.', { score })}</div></div>
    {:else if info.state === 'finished'}
      <div class="verdict good"><div class="headline">{t('Finished')}</div></div>
    {:else}
      <div class="verdict" class:good={info.darts_to_finish === 1} class:ok={info.darts_to_finish > 1} class:bad={info.darts_to_finish == null}>
        <div class="headline">{t('{rest} left', { rest: info.rest })}</div>
        {#if info.darts_to_finish}
          <div class="line">{t('Finish with {darts}', { darts: dartsText(info.darts_to_finish) })}:
            <RouteChips route={info.route} /></div>
        {:else}
          <div class="line">{t('No finish with the {n} darts left', { n: info.darts_left })}</div>
        {/if}
      </div>
    {/if}

    <div class="actions">
      <button class="btn" onclick={next}>{t('Next score')}</button>
      <button class="btn ghost" onclick={undoDart} disabled={!fields.length}>{t('↩ Undo dart')}</button>
    </div>
  </div>
  <div class="board">
    <DartBoard onSelect={tap} disabled={score == null || fields.length >= 3 || (info && info.state !== 'open')} />
  </div>
</div>

<style>
  .chips { display: flex; gap: 0.4rem; margin-bottom: 1.25rem; flex-wrap: wrap; }
  .chip { background: var(--glass); border: 1px solid var(--glass-border); color: var(--muted); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2); border-radius: 20px; padding: 0.35rem 1rem; font-family: inherit; font-size: 0.85rem; cursor: pointer; }
  .chip:hover { border-color: var(--accent); color: var(--text); }
  .chip.active { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); font-weight: 700; }
  .shots { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr); gap: 1.5rem; align-items: start; }
  .left { display: flex; flex-direction: column; gap: 1rem; background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); border-radius: 16px; padding: 1.5rem; }
  .caption { font-size: 0.8rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: -0.6rem; }
  .score { font-size: clamp(4rem, 12vw, 8rem); font-weight: 900; line-height: 1; color: var(--accent); }
  .hint { color: var(--muted); display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
  .darts { display: flex; gap: 0.6rem; }
  .dart { flex: 1; text-align: center; padding: 0.4em 0; font-weight: 800; font-size: 1.6rem; background: var(--glass); border: 1px solid var(--glass-border); border-radius: 12px; }
  .dart.empty { color: var(--muted); }
  .verdict { display: flex; flex-direction: column; gap: 0.5rem; padding: 0.9rem 1rem; border-radius: 12px; border: 1px solid var(--glass-border); background: rgba(0, 0, 0, 0.18); }
  .verdict.good { border-color: var(--green); }
  .verdict.ok { border-color: var(--accent); }
  .verdict.bad { border-color: var(--red); }
  .headline { font-weight: 800; font-size: 1.3rem; }
  .good .headline { color: var(--green); }
  .ok .headline { color: var(--accent); }
  .bad .headline { color: var(--red); }
  .line { color: var(--muted); display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
  .actions { display: flex; gap: 0.6rem; flex-wrap: wrap; }
  .btn { border: none; border-radius: 8px; padding: 0.65rem 1.4rem; font-size: 0.95rem; font-weight: 600; cursor: pointer; background: #166534; color: #fff; }
  .btn.ghost { background: var(--glass); color: color-mix(in srgb, var(--text) 82%, transparent); border: 1px solid var(--glass-border); }
  .btn.ghost:hover:not(:disabled) { border-color: var(--accent); color: var(--text); }
  .btn:disabled { opacity: 0.5; cursor: default; }
  .board { display: flex; justify-content: center; --board-max: min(70vh, 100%); }
  @media (max-width: 760px) { .shots { grid-template-columns: 1fr; } }
</style>
