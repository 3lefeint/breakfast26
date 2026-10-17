<script>
  import { t } from '../i18n.js';
  // Where a Warm-up run stands: the seven stations with the fields done in each, and the fields of the
  // station that is up as pills, the ones done filled and the one that is up marked.
  import { stationName, fieldLabel } from '../warmUp.js';

  let { wu } = $props();

  let stations = $derived.by(() => {
    const rows = new Map(wu.stations.map((s) => [s.index, { index: s.index, kind: s.kind, total: 0, done: 0 }]));
    wu.steps.forEach(([, , station], index) => {
      const row = rows.get(station);
      row.total += 1;
      if (index < wu.position) row.done += 1;
    });
    return [...rows.values()];
  });
  let current = $derived(wu.target.station);
  let fields = $derived(wu.steps
    .map(([kind, number, station], index) => ({ kind, number, station, index }))
    .filter((f) => f.station === current));
</script>

<div class="progress" aria-label={t('Progress')}>
  <div class="stations" role="list">
    {#each stations as s (s.index)}
      <div class="station" role="listitem" class:done={s.done === s.total} class:now={!wu.complete && s.index === current}>
        <span class="name">{stationName(s.kind)}</span>
        <span class="bar"><span class="fill" style="width: {(s.done / s.total) * 100}%"></span></span>
        <span class="count">{s.done}/{s.total}</span>
      </div>
    {/each}
  </div>
  {#if fields.length > 1}
    <div class="pills" role="list" aria-label={t('Fields of the station')}>
      {#each fields as f}
        <span class="pill" role="listitem" class:done={wu.complete || f.index < wu.position}
              class:now={!wu.complete && f.index === wu.position}>{f.number}</span>
      {/each}
    </div>
  {/if}
</div>

<style>
  .progress { display: flex; flex-direction: column; gap: 0.8rem; }
  .stations { display: flex; flex-direction: column; gap: 0.3rem; }
  .station { display: grid; grid-template-columns: minmax(0, 9em) minmax(0, 1fr) 3.4em; align-items: center; gap: 0.6rem; padding: 0.15em 0.5em; border: 1px solid transparent; border-radius: 8px; }
  .station.now { border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 25%, transparent); }
  .name { font-size: 0.8em; color: var(--muted); font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .station.now .name { color: var(--accent); }
  .bar { display: block; height: 0.4em; border-radius: 999px; background: color-mix(in srgb, var(--text) 14%, transparent); overflow: hidden; }
  .fill { display: block; height: 100%; background: var(--accent); }
  .station.done .fill { background: var(--green); }
  .count { font-size: 0.8em; font-weight: 700; text-align: right; }
  .pills { display: flex; flex-wrap: wrap; gap: 0.3rem; }
  .pill {
    min-width: 2.4em; text-align: center; padding: 0.15em 0.5em; border-radius: 999px;
    border: 1px solid var(--border); color: var(--muted); font-size: 0.8em; font-weight: 700;
  }
  .pill.done { background: var(--accent); border-color: var(--accent); color: #0c0c0f; }
  .pill.now { border-color: var(--accent); color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 30%, transparent); }
</style>
