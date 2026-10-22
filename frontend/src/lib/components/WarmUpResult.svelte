<script>
  import { t } from '../i18n.js';
  // The result of a finished Warm-up run: the darts it took (or how far the player got), how it compares with
  // the earlier complete runs of the same player, the darts per station, the fields that needed the most
  // darts and where the darts landed. Shown on Home and on the TV.
  import DartBoard from './DartBoard.svelte';
  import { fieldLabel, modeLabel, runDots, stationName } from '../warmUp.js';
  import { shownName } from '../util.js';

  let { wu, large = false } = $props();

  let r = $derived(wu.result || {});
  let total = $derived(wu.steps.length);
  let before = $state(null);

  // The earlier complete runs of this player over the same stations, this run left out.
  $effect(() => {
    const id = wu.match_id;
    const player = wu.player;
    const key = wu.kinds.join(',');
    fetch('/api/stats/warm-up/overview')
      .then((res) => res.json())
      .then((body) => {
        const runs = (body.players || []).find((p) => p.player === player)?.modes.find((m) => m.key === key)?.runs || [];
        const earlier = runs.filter((run) => run.complete && run.match_id !== id);
        before = earlier.length ? {
          runs: earlier.length,
          best: Math.min(...earlier.map((run) => run.darts)),
          average: Math.round((earlier.reduce((sum, run) => sum + run.darts, 0) / earlier.length) * 10) / 10,
        } : { runs: 0 };
      })
      .catch(() => { before = null; });
  });
</script>

<div class="result" class:large>
  <div class="headline">
    {#if r.complete}
      <div class="points">{r.darts}<span class="unit">{wu.all ? t('darts for all {total} fields', { total }) : t('darts for {total} fields', { total })}</span></div>
    {:else}
      <div class="points">{r.fields}<span class="unit">{t('of {total} fields', { total })}</span></div>
    {/if}
    <div class="meta">{shownName(wu.player)}{wu.all ? '' : ' · ' + modeLabel(wu.kinds)}{r.complete ? '' : ' · ' + t('{n} darts', { n: r.darts })}</div>
    {#if before}
      <div class="compare">
        {#if r.complete && before.runs && r.darts < before.best}
          <span class="best">{t('New best, the one before was {n} darts', { n: before.best })}</span>
        {:else if before.runs}
          {t('Best before {best} darts, average {average} darts ({runs} runs)', before)}
        {:else if r.complete}
          {t('The first complete run')}
        {/if}
      </div>
    {/if}
  </div>

  <div class="content">
    <div class="left">
      <table class="stations">
        <thead><tr><th>{t('Station')}</th><th class="num">{t('Fields')}</th><th class="num">{t('Darts')}</th></tr></thead>
        <tbody>
          {#each r.stations || [] as s}
            <tr><td>{stationName(s.kind)}</td><td class="num">{s.fields}</td><td class="num">{s.darts}</td></tr>
          {/each}
        </tbody>
      </table>
      {#if r.slowest?.length}
        <div class="slow">
          <div class="caption">{t('Fields that needed the most darts')}</div>
          {#each r.slowest as f}
            <span class="chip">{fieldLabel(f.kind, f.number)} <b>{f.darts}</b></span>
          {/each}
        </div>
      {/if}
    </div>
    <div class="board"><DartBoard readonly darts={runDots(wu)} /></div>
  </div>
</div>

<style>
  .result { display: flex; flex-direction: column; gap: 1.2rem; }
  .headline { display: flex; flex-direction: column; gap: 0.4rem; }
  .points { font-size: 3rem; font-weight: 900; color: var(--accent); line-height: 1; }
  .unit { font-size: 1rem; color: var(--muted); font-weight: 600; margin-left: 0.5rem; }
  .meta { color: var(--muted); font-size: 0.9rem; }
  .compare { color: var(--muted); font-size: 0.9rem; }
  .best { color: var(--green); font-weight: 700; }
  .content { display: grid; grid-template-columns: 1fr minmax(0, 18rem); gap: 1.2rem; align-items: start; }
  .left { display: flex; flex-direction: column; gap: 1rem; }
  .stations { width: 100%; border-collapse: collapse; }
  .stations th { font-size: 0.75rem; color: var(--muted); font-weight: 500; text-align: left; padding: 0.3rem 0.5rem; border-bottom: 1px solid var(--glass-border); }
  .stations td { padding: 0.35rem 0.5rem; border-bottom: 1px solid var(--glass-border); font-size: 0.85rem; }
  .num { text-align: right; }
  .stations th.num { text-align: right; }
  .slow { display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: center; }
  .caption { width: 100%; font-size: 0.7rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
  .chip { border: 1px solid var(--glass-border); border-radius: 999px; padding: 0.15em 0.7em; font-size: 0.85rem; }
  .chip b { color: var(--accent); margin-left: 0.2em; }
  .large .points { font-size: clamp(3rem, 8vw, 7rem); }
  .large .meta, .large .compare { font-size: clamp(0.9rem, 1.6vw, 1.5rem); }
  .large .content { grid-template-columns: 1fr minmax(0, min(36vw, 50vh)); }
  .large .left { font-size: clamp(0.9rem, 1.5vw, 1.4rem); }
  @media (max-width: 640px) { .content { grid-template-columns: 1fr; } }
</style>
