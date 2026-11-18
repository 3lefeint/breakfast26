<script>
  import { t } from '../../lib/i18n.js';
  // The first setup of the dart detection at a new board, shown on the Board page while the detection has no board model: the board is
  // emptied, the detection looks for it in every camera's picture, the player clicks on the 20 in each picture and the model is fitted.
  import { apiJson } from '../../lib/api.js';

  let { status, tick, onchange = () => {} } = $props();

  let busy = $state(false);
  let setup = $derived(status.setup);
  let searched = $derived(setup.cameras.some((c) => c.found));

  const PROBLEMS = {
    not_found: (cams) => `${t('Board not found in camera')} ${cams.map((c) => c + 1).join(', ')}. ${t('Is the board empty and well lit, and does it show completely?')}`,
    no_pictures: (cams) => `${t('No picture yet from camera')} ${cams.map((c) => c + 1).join(', ')}.`,
    not_ready: () => t('Click on the 20 in every picture first.'),
    failed: () => t('Something went wrong. Try again.'),
  };

  async function post(path, body) {
    busy = true;
    const res = await apiJson('POST', path, body ?? {});
    busy = false;
    if (res.error) alert(t(res.error));
    onchange();
  }

  async function click(i, ev) {
    if (!setup.cameras[i].found || setup.busy) return;
    const img = ev.currentTarget;
    const box = img.getBoundingClientRect();
    // the picture is shown cropped to 4:3 and scaled: map the click back to picture pixels
    const scale = Math.max(box.width / img.naturalWidth, box.height / img.naturalHeight);
    const x = (ev.clientX - box.left - (box.width - img.naturalWidth * scale) / 2) / scale;
    const y = (ev.clientY - box.top - (box.height - img.naturalHeight * scale) / 2) / scale;
    await post('/api/detection/setup/click', { cam: i, x, y });
  }
</script>

<div class="section">
  <div class="section-title">{t('Set up the dart detection')}</div>
  <p class="intro">{t('This board has no model yet. Take the darts out of the board. The detection looks for the board in every picture; then click on the 20 in each one.')}</p>

  <div class="actions">
    <button class="btn" disabled={busy || setup.busy} onclick={() => post('/api/detection/setup/search')}>{searched ? t('Search again') : t('Search the board')}</button>
    <button class="btn primary" disabled={busy || setup.busy || !setup.ready} onclick={() => post('/api/detection/setup/fit')}>{t('Make the model')}</button>
  </div>

  {#if setup.busy}
    <div class="progress" role="progressbar" aria-valuenow={Math.round((setup.progress?.fraction ?? 0) * 100)} aria-valuemin="0" aria-valuemax="100">
      <span class="spinner" aria-hidden="true"></span>
      <div class="track"><div class="fill" style="width: {Math.round((setup.progress?.fraction ?? 0) * 100)}%"></div></div>
      <span class="pct">{Math.round((setup.progress?.fraction ?? 0) * 100)} %</span>
      <span class="muted">{setup.busy === 'search' ? t('Looking for the board…') : t('Making the model…')}</span>
    </div>
  {/if}
  {#if setup.problem}
    <div class="problem" role="alert">{(PROBLEMS[setup.problem.kind] ?? PROBLEMS.failed)(setup.problem.cams)}</div>
  {/if}

  <div class="cams">
    {#each setup.cameras as c, i (i)}
      <figure>
        <img class:pick={c.found && !c.clicked} src={`/api/detection/frame/${i}?t=${tick}`} alt={`${t('Camera')} ${i + 1}`} onclick={(ev) => click(i, ev)}>
        <figcaption class:bad={status.cameras[i]?.error}>
          {t('Camera')} {i + 1}:
          {#if status.cameras[i]?.error}{status.cameras[i].error === 'in use' ? t('in use by another program') : t('not found')}
          {:else if c.clicked}{t('20 set')}
          {:else if c.found}{t('click on the 20')}
          {:else}{t('board not searched yet')}{/if}
        </figcaption>
      </figure>
    {/each}
  </div>
</div>

<style>
  .section { background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); border-radius: 16px; padding: 1.25rem; margin-bottom: 1rem; }
  .section-title { font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 0.7rem; }
  .intro { margin: 0 0 1rem; }
  .muted { color: var(--muted); }
  .actions { display: flex; gap: 0.7rem; flex-wrap: wrap; margin-bottom: 1rem; }
  .btn { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 10px; padding: 0.45rem 1rem; font: inherit; cursor: pointer; }
  .btn:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
  .btn.primary { border-color: var(--accent); }
  .btn:disabled { opacity: 0.5; cursor: default; }
  .problem { border: 1px solid var(--yellow, #e0a73a); color: var(--yellow, #e0a73a); border-radius: 10px; padding: 0.6rem 0.9rem; margin-bottom: 1rem; font-size: 0.9rem; }
  .progress { display: flex; align-items: center; gap: 0.8rem; margin-bottom: 1rem; }
  .progress .track { flex: 1; height: 10px; border-radius: 5px; background: var(--glass); border: 1px solid var(--glass-border); overflow: hidden; }
  .progress .fill { height: 100%; background: var(--accent); transition: width 0.4s; }
  .progress .pct { font-variant-numeric: tabular-nums; min-width: 3rem; text-align: right; }
  .spinner { width: 1.1rem; height: 1.1rem; border-radius: 50%; border: 2px solid var(--glass-border); border-top-color: var(--accent); animation: spin 0.9s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .cams { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.8rem; }
  @media (max-width: 900px) { .cams { grid-template-columns: 1fr; } }
  figure { margin: 0; }
  img { width: 100%; display: block; border-radius: 10px; border: 1px solid var(--glass-border); background: #000; aspect-ratio: 4 / 3; object-fit: cover; }
  img.pick { cursor: crosshair; border-color: var(--accent); }
  figcaption { color: var(--muted); font-size: 0.8rem; margin-top: 0.3rem; }
  figcaption.bad { color: var(--red); }
</style>
