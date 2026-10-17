<script>
  import { t } from '../../lib/i18n.js';
  // The board page: what the own dart detection sees. Live pictures of the cameras with the board model drawn in, the state of the
  // board, the last events, and the buttons for a new empty-board picture and the automatic calibration. Without the own detection
  // (the board manager of Autodarts is the source) there is nothing to show here.
  import { onMount } from 'svelte';
  import { apiJson } from '../../lib/api.js';
  import PageHeader from '../../lib/components/PageHeader.svelte';

  let status = $state(null);
  let tick = $state(Date.now());
  let busy = $state(false);

  async function load() {
    try {
      status = await fetch('/api/detection/status').then((r) => r.json());
    } catch (_) {
      status = { enabled: true, reachable: false };
    }
    tick = Date.now();
  }
  onMount(() => {
    load();
    const id = setInterval(load, 1200);
    return () => clearInterval(id);
  });

  async function post(path, confirmText) {
    if (confirmText && !confirm(confirmText)) return;
    busy = true;
    const res = await apiJson('POST', path, {});
    busy = false;
    if (res.error) alert(t(res.error));
    load();
  }

  const BOARD_STATE = { ready: () => t('Ready'), takeout: () => t('Pull the darts'), blocked: () => t('Blocked: something is in the way'), starting: () => t('Starting'), no_cameras: () => t('No cameras') };
  const NOT_RUNNING = { no_model: () => t('No board model yet: the dart detection cannot start.') };
  let cams = $derived(status?.cameras ?? []);
  let board = $derived(status?.board ?? null);
</script>

<PageHeader title={t('Board')} subtitle={t('Cameras and dart detection')} />

{#if !status}
  <div class="section muted">{t('Waiting for the pictures…')}</div>
{:else if !status.enabled}
  <div class="section muted">{t('The dart detection is off. Switch it on with [cameras] enabled = true in config.toml.')}</div>
{:else if !status.reachable}
  <div class="section warn">{(NOT_RUNNING[status.status] ?? (() => t('The dart detection is not reachable.')))()}</div>
{:else}
  <div class="section">
    <div class="state-row">
      <span class="pill" class:ok={board.status === 'ready'} class:warn={board.status === 'blocked' || board.status === 'no_cameras'}>{(BOARD_STATE[board.status] ?? (() => board.status))()}</span>
      <span class="darts">{t('Darts on the board')}: <b>{board.count}</b> {#if board.throws.length}<span class="muted">({board.throws.join(', ')})</span>{/if}</span>
      <span class="spacer"></span>
      <button class="btn" disabled={busy} onclick={() => post('/api/detection/reset')}>{t('Empty board = now')}</button>
      <button class="btn" disabled={busy || status.busy} onclick={() => post('/api/detection/calibrate', t('The calibration needs an empty board and takes about a minute. Start?'))}>
        {status.busy ? t('Calibrating…') : t('Calibrate (empty board)')}
      </button>
    </div>
    <div class="cams">
      {#each cams as c, i (i)}
        <figure>
          <img src={`/api/detection/frame/${i}?t=${tick}`} alt={`${t('Camera')} ${i + 1}`}>
          <figcaption class:bad={c.error}>{t('Camera')} {i + 1}: {c.error ? c.error : `${c.fps} fps`}</figcaption>
        </figure>
      {/each}
    </div>
  </div>

  <div class="two">
    <div class="section">
      <div class="section-title">{t('Events')}</div>
      <table>
        <tbody>
          {#each status.events.slice(0, 12) as e (e.n)}
            <tr class={`k-${e.kind}`}><td class="mono">{e.t}</td><td>{e.kind}</td><td>{e.count}</td><td>{e.field ?? ''}</td></tr>
          {/each}
        </tbody>
      </table>
    </div>
    <div class="section">
      <div class="section-title">{t('Notes')}</div>
      {#each status.notes as n (n.t + n.text)}<p class="note"><span class="mono">{n.t}</span> {n.text}</p>{/each}
      <div class="section-title" style="margin-top:1rem">{t('Load')}</div>
      <p class="note">{status.load.looks_per_s} / s · {status.load.feed_ms} ms</p>
    </div>
  </div>
{/if}

<style>
  .section { background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); border-radius: 16px; padding: 1.25rem; margin-bottom: 1rem; }
  .section-title { font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 0.7rem; }
  .muted { color: var(--muted); }
  .warn { color: var(--yellow, #e0a73a); }
  .state-row { display: flex; align-items: center; gap: 0.9rem; flex-wrap: wrap; margin-bottom: 1rem; }
  .spacer { flex: 1; }
  .pill { border-radius: 999px; padding: 0.2rem 0.8rem; background: var(--glass); border: 1px solid var(--glass-border); font-weight: 700; }
  .pill.ok { color: var(--green); border-color: var(--green); }
  .pill.warn { color: var(--yellow, #e0a73a); border-color: var(--yellow, #e0a73a); }
  .btn { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 10px; padding: 0.45rem 1rem; font: inherit; cursor: pointer; }
  .btn:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
  .btn:disabled { opacity: 0.5; cursor: default; }
  .cams { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.8rem; }
  @media (max-width: 900px) { .cams { grid-template-columns: 1fr; } }
  figure { margin: 0; }
  img { width: 100%; display: block; border-radius: 10px; border: 1px solid var(--glass-border); background: #000; aspect-ratio: 4 / 3; object-fit: cover; }
  figcaption { color: var(--muted); font-size: 0.8rem; margin-top: 0.3rem; }
  figcaption.bad { color: var(--red); }
  .two { display: grid; grid-template-columns: 3fr 2fr; gap: 1rem; }
  @media (max-width: 900px) { .two { grid-template-columns: 1fr; } }
  table { border-collapse: collapse; width: 100%; font-size: 0.85rem; }
  td { padding: 0.25rem 0.5rem; border-bottom: 1px solid var(--glass-border); }
  .mono { font-family: ui-monospace, Menlo, monospace; color: var(--muted); }
  tr.k-dart td:nth-child(2) { color: var(--green); }
  tr.k-unclear td:nth-child(2), tr.k-moved td:nth-child(2) { color: var(--yellow, #e0a73a); }
  .note { margin: 0 0 0.3rem; font-size: 0.85rem; }
</style>
