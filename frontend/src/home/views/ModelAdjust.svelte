<script>
  import { t } from '../../lib/i18n.js';
  // Manual adjustment of the board model, as the calibration page of the first tests had it: 17 points per camera (the center and the
  // crossings of the four sector wires with the four outer rings) are dragged onto what they belong to; the model (a homography per
  // camera and the ring radii) is fitted to all of them again when a point is let go and the rings and wires are redrawn. A magnifier shows
  // the spot while dragging, the picture can be zoomed (wheel, buttons) and moved. Save makes the worker use the model (the previous
  // one is kept and can be taken back).
  import { onMount } from 'svelte';
  import { apiJson } from '../../lib/api.js';
  import { ringPath, wirePath } from '../../lib/boardModel.js';

  let { onclose = () => {} } = $props();

  const GRAB = 48;            // screen pixels: a touch picks the point nearest to it within this distance
  const LOUPE_R = 70;         // screen pixels
  const LOUPE_ZOOM = 12;
  const RINGS = [170, 162, 107, 99, 15.9, 6.35];
  const WIRES = Array.from({ length: 20 }, (_, k) => 9 + 18 * k);
  const WIRE_NAMES = { 9: '20 | 1', 99: '6 | 10', 189: '3 | 19', 279: '11 | 14' };

  let state = $state(null);
  let cam = $state(0);
  let view = $state({ x: 0, y: 0, w: 800, h: 600 });
  let drag = $state(null);          // { id, startX, startY, orig, cur }
  let pan = $state(null);
  let selected = $state(null);
  let stamp = $state(Date.now());
  let message = $state('');
  let saving = $state(false);
  let svg = $state(null);
  let nudge = null;
  let canvas = $state(null);
  let loupeCanvas = $state(null);
  let stage = $state(null);
  let picture = $state(null);        // the loaded camera picture, drawn on the canvas below the overlay

  async function load(res) {
    state = res ?? (await fetch('/api/detection/model').then((r) => r.json()));
    if (state.error) { message = t(state.error); state = null; return; }
    if (view.w === 800 && view.h === 600) fit();
  }
  onMount(() => load());

  // The picture is drawn on a canvas (only the part that is in view): an SVG image zoomed to 40 times is too big for the browser to draw
  // and comes out as black patches. Sharp pixels from a zoom of 3 on, smoothed below.
  $effect(() => {
    const url = `/api/detection/frame/${cam}?raw=1&t=${stamp}`;
    const im = new Image();
    im.onload = () => { picture = im; };
    im.src = url;
  });
  $effect(() => {
    if (!canvas || !picture) return;
    const box = canvas.getBoundingClientRect();
    const d = window.devicePixelRatio || 1;
    canvas.width = Math.round(box.width * d);
    canvas.height = Math.round(box.height * d);
    const g = canvas.getContext('2d');
    g.imageSmoothingEnabled = canvas.width / view.w < 3 * d;
    g.drawImage(picture, view.x, view.y, view.w, view.h, 0, 0, canvas.width, canvas.height);
  });

  const width = $derived(state?.size?.[0] ?? 800);
  const height = $derived(state?.size?.[1] ?? 600);
  const points = $derived(state?.points?.[String(cam)] ?? {});
  const flat = $derived(state?.H?.[String(cam)]?.flat() ?? null);
  const scale = $derived(svg ? svg.getBoundingClientRect().width / view.w : 1);       // screen pixels per picture pixel
  const edited = $derived(state?.edited?.[String(cam)] ?? []);
  const anyEdited = $derived(!!state?.dirty || Object.values(state?.edited ?? {}).some((l) => l.length));
  let auto = $state(null);          // the status of the automatic fit while it runs: { fraction, text }

  function fit() { view = { x: 0, y: 0, w: width, h: height }; }
  function zoomAt(factor, cx, cy) {                              // cx, cy: a point in picture pixels that stays where it is
    const w = Math.min(width, Math.max(width / 40, view.w / factor));
    const h = w * height / width;
    const fx = (cx - view.x) / view.w, fy = (cy - view.y) / view.h;
    view = { x: Math.min(Math.max(0, cx - fx * w), width - w), y: Math.min(Math.max(0, cy - fy * h), height - h), w, h };
  }
  function toImage(e) {
    const m = svg.getScreenCTM().inverse();
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(m);
    return [p.x, p.y];
  }
  function toScreen(x, y) {
    const b = svg.getBoundingClientRect();
    return [b.left + ((x - view.x) / view.w) * b.width, b.top + ((y - view.y) / view.h) * b.height];
  }

  function nearest(e) {
    let best = null, bd = GRAB;
    for (const [id, p] of Object.entries(points)) {
      const [sx, sy] = toScreen(p[0], p[1]);
      const d = Math.hypot(sx - e.clientX, sy - e.clientY);
      if (d < bd) { bd = d; best = id; }
    }
    return best;
  }

  function down(e) {
    e.preventDefault();
    svg.setPointerCapture(e.pointerId);
    svg.focus({ preventScroll: true });
    const id = nearest(e);
    if (id) {
      selected = id;
      drag = { id, pid: e.pointerId, sx: e.clientX, sy: e.clientY, orig: points[id].slice(), cur: points[id].slice() };
    } else {
      pan = { pid: e.pointerId, x: e.clientX, y: e.clientY };
    }
  }
  function move(e) {
    if (drag && drag.pid === e.pointerId) {
      const x = drag.orig[0] + (e.clientX - drag.sx) / scale, y = drag.orig[1] + (e.clientY - drag.sy) / scale;
      drag.cur = [Math.min(width, Math.max(0, x)), Math.min(height, Math.max(0, y))];
    } else if (pan && pan.pid === e.pointerId) {
      const dx = (e.clientX - pan.x) / scale, dy = (e.clientY - pan.y) / scale;
      view = { ...view, x: Math.min(Math.max(0, view.x - dx), width - view.w), y: Math.min(Math.max(0, view.y - dy), height - view.h) };
      pan = { ...pan, x: e.clientX, y: e.clientY };
    }
  }
  async function up(e) {
    if (drag && drag.pid === e.pointerId) {
      const d = drag;
      drag = null;
      await commit(d.id, d.cur);
    }
    if (pan && pan.pid === e.pointerId) pan = null;
  }
  function wheel(e) {
    e.preventDefault();
    const [x, y] = toImage(e);
    zoomAt(e.deltaY < 0 ? 1.25 : 1 / 1.25, x, y);
  }
  async function commit(id, xy) {
    const res = await apiJson('POST', '/api/detection/model/move', { cam, id, xy });
    if (res.error) { message = t(res.error); return; }
    await load(res);
  }
  function key(e) {
    if (!selected) return;
    const step = e.shiftKey ? 3 : 0.25;
    const d = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
    if (!d) return;
    e.preventDefault();
    const p = points[selected];
    state.points[String(cam)][selected] = [p[0] + d[0], p[1] + d[1]];
    clearTimeout(nudge);
    const id = selected, xy = state.points[String(cam)][id];
    nudge = setTimeout(() => commit(id, xy), 350);
  }

  async function fitAutomatically() {
    if (!confirm(t('Replace all points with the automatic fit? Points you moved by hand are lost. The board must be empty.'))) return;
    const res = await apiJson('POST', '/api/detection/model/auto', {});
    if (res.error) { message = t(res.error); return; }
    auto = { fraction: 0, text: '' };
    for (;;) {
      await new Promise((r) => setTimeout(r, 1200));
      const st = await fetch('/api/detection/status').then((r) => r.json()).catch(() => null);
      if (!st || !st.busy) break;
      auto = st.progress ?? auto;
    }
    auto = null;
    message = t('The automatic fit moved the points. Look at them, correct what is off and save.');
    await load();
  }

  async function save() {
    saving = true;
    const res = await apiJson('POST', '/api/detection/model/save', {});
    saving = false;
    message = res.error ? t(res.error) : t('Saved. The next still picture is taken as the empty board.');
    await load();
  }
  async function discard() {
    const res = await apiJson('POST', '/api/detection/model/discard', {});
    message = '';
    await load(res);
  }
  async function revert() {
    if (!confirm(t('Take the previous model back?'))) return;
    const res = await apiJson('POST', '/api/detection/model/revert', {});
    message = res.error ? t(res.error) : t('The previous model is back.');
    await load();
  }

  // The magnifier is a canvas of its own in screen pixels (an SVG image scaled that much on top of a deep zoom came out as black patches):
  // it sits above the dragged point (below it near the upper edge) and shows the picture around it, LOUPE_ZOOM times as large.
  const loupe = $derived.by(() => {
    if (!drag || !stage) return null;
    const b = stage.getBoundingClientRect();
    const sx = ((drag.cur[0] - view.x) / view.w) * b.width, sy = ((drag.cur[1] - view.y) / view.h) * b.height;
    let ly = sy - 150;
    if (ly - LOUPE_R < 4) ly = sy + 150;
    const lx = Math.min(Math.max(sx, LOUPE_R + 4), b.width - LOUPE_R - 4);
    return { left: lx - LOUPE_R, top: ly - LOUPE_R };
  });
  $effect(() => {
    if (!loupe || !loupeCanvas || !picture) return;
    const d = window.devicePixelRatio || 1, size = 2 * LOUPE_R;
    loupeCanvas.width = Math.round(size * d);
    loupeCanvas.height = Math.round(size * d);
    const g = loupeCanvas.getContext('2d');
    g.scale(d, d);
    const half = LOUPE_R / LOUPE_ZOOM;
    g.beginPath(); g.arc(LOUPE_R, LOUPE_R, LOUPE_R, 0, 7); g.clip();
    g.fillStyle = '#000'; g.fillRect(0, 0, size, size);
    g.imageSmoothingEnabled = false;
    g.drawImage(picture, drag.cur[0] - half, drag.cur[1] - half, 2 * half, 2 * half, 0, 0, size, size);
    g.strokeStyle = '#ff3b30'; g.lineWidth = 1.5; g.beginPath();
    g.moveTo(LOUPE_R - 20, LOUPE_R); g.lineTo(LOUPE_R + 20, LOUPE_R); g.moveTo(LOUPE_R, LOUPE_R - 20); g.lineTo(LOUPE_R, LOUPE_R + 20); g.stroke();
  });
  const rep = $derived(state?.report);
</script>

<div class="adjust">
  <p class="hint">{t('Drag a point onto what it belongs to: the center and the crossings of the wires 20|1, 6|10, 3|19 and 11|14 with the four outer rings. A touch picks the nearest point; the magnifier shows the spot. Scroll wheel or + and − zoom, dragging the picture moves it, arrow keys nudge the chosen point.')}</p>

  <div class="bar">
    {#each [0, 1, 2] as c (c)}
      <button type="button" class="chip" class:on={cam === c} onclick={() => { cam = c; selected = null; }}>{t('Camera')} {c + 1}</button>
    {/each}
    <span class="gap"></span>
    <button type="button" class="chip" onclick={() => zoomAt(1.5, view.x + view.w / 2, view.y + view.h / 2)}>+</button>
    <button type="button" class="chip" onclick={() => zoomAt(1 / 1.5, view.x + view.w / 2, view.y + view.h / 2)}>−</button>
    <button type="button" class="chip" onclick={fit}>{t('Fit view')}</button>
    <button type="button" class="chip" onclick={() => (stamp = Date.now())}>{t('New picture')}</button>
    <button type="button" class="chip" disabled={!!auto} onclick={fitAutomatically}>{t('Fit automatically')}</button>
  </div>
  {#if auto}
    <div class="progress"><span class="spinner" aria-hidden="true"></span>
      <div class="track"><div class="fill" style="width: {Math.round((auto.fraction ?? 0) * 100)}%"></div></div>
      <span class="pct">{Math.round((auto.fraction ?? 0) * 100)} %</span><span class="muted">{auto.text ?? ''}</span></div>
  {/if}

  {#if state && flat}
    <div class="stage" bind:this={stage}>
    <canvas bind:this={canvas} aria-hidden="true"></canvas>
    <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
    <svg bind:this={svg} viewBox="{view.x} {view.y} {view.w} {view.h}" tabindex="0" role="application" aria-label={t('Board model of the camera')}
         onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={up} onwheel={wheel} onkeydown={key}>
      {#each RINGS as r (r)}<path d={ringPath(flat, r, state.radii)} class="ring" />{/each}
      {#each WIRES as a (a)}<path d={wirePath(flat, a, state.radii)} class="wire" />{/each}
      {#each Object.entries(points) as [id, p] (id)}
        {@const q = drag && drag.id === id ? drag.cur : p}
        {@const hand = edited.includes(id) || (drag && drag.id === id)}
        <g transform={`translate(${q[0]} ${q[1]})`} class="pt" class:hand class:sel={selected === id}>
          <circle r={7 / scale} />
          <path d={`M${-3 / scale} 0 H${3 / scale} M0 ${-3 / scale} V${3 / scale}`} />
        </g>
      {/each}
      {#if selected && points[selected]}
        {@const q = drag && drag.id === selected ? drag.cur : points[selected]}
        {@const tg = state.targets.find((x) => x.id === selected)}
        <text x={q[0]} y={q[1] - 12 / scale} font-size={13 / scale} text-anchor="middle" class="label" style="stroke-width: {3 / scale}px">
          {tg.id === 'center' ? t('Center') : `${tg.r} mm · ${WIRE_NAMES[tg.a]}`}
        </text>
      {/if}
    </svg>
    {#if loupe}<canvas bind:this={loupeCanvas} class="loupe" style="left: {loupe.left}px; top: {loupe.top}px; width: {2 * LOUPE_R}px; height: {2 * LOUPE_R}px" aria-hidden="true"></canvas>{/if}
    </div>
  {:else}
    <p class="muted">{message || t('Waiting for the pictures…')}</p>
  {/if}

  {#if rep}
    <pre class="rep">{t('Ring radii (mm)')}: {Object.entries(rep.radii_mm).map(([a, b]) => `${a} → ${b}`).join(', ')}
{t('Distance of the points to the model (px)')}: {Object.keys(rep.rms_px).map((c) => `${t('Camera')} ${+c + 1} ${rep.rms_px[c]} (max ${rep.max_px[c]})`).join(', ')}
{t('Moved by hand')}: {Object.keys(state.edited).map((c) => `${t('Camera')} ${+c + 1}: ${state.edited[c].length}`).join(', ')}</pre>
    {#if rep.unusual.length}<p class="warn">{t('Check the overlay')}: {rep.unusual.join('; ')}</p>{/if}
  {/if}

  <div class="bar">
    <button class="btn" disabled={!anyEdited || saving} onclick={save}>{saving ? t('Saving…') : t('Save')}</button>
    <button class="btn" disabled={!anyEdited} onclick={discard}>{t('Discard changes')}</button>
    <button class="btn" disabled={!state?.can_revert} onclick={revert}>{t('Previous model')}</button>
    <button class="btn" onclick={onclose}>{t('Close')}</button>
    <span class="muted msg">{message}</span>
  </div>
</div>

<style>
  .adjust { display: flex; flex-direction: column; gap: 0.8rem; }
  .hint, .muted { color: var(--muted); font-size: 0.85rem; margin: 0; }
  .warn { color: var(--yellow, #e0a73a); margin: 0; font-size: 0.85rem; }
  .bar { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
  .gap { flex: 1; }
  .progress { display: flex; align-items: center; gap: 0.8rem; }
  .progress .track { flex: 1; height: 10px; border-radius: 5px; background: var(--glass); border: 1px solid var(--glass-border); overflow: hidden; }
  .progress .fill { height: 100%; background: var(--accent); transition: width 0.4s; }
  .progress .pct { font-variant-numeric: tabular-nums; min-width: 3rem; text-align: right; }
  .spinner { width: 1.1rem; height: 1.1rem; border-radius: 50%; border: 2px solid var(--glass-border); border-top-color: var(--accent); animation: spin 0.9s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .chip:disabled { opacity: 0.5; cursor: default; }
  .msg { margin-left: 0.5rem; }
  .stage { position: relative; width: 100%; aspect-ratio: 4 / 3; background: #000; border-radius: 10px; border: 1px solid var(--glass-border); overflow: hidden; }
  canvas { position: absolute; inset: 0; width: 100%; height: 100%; }
  svg { position: absolute; inset: 0; width: 100%; height: 100%; touch-action: none; outline: none; user-select: none; cursor: crosshair; }
  .ring { fill: none; stroke: #46ff46; stroke-opacity: 0.9; stroke-width: 1; vector-effect: non-scaling-stroke; }
  .wire { fill: none; stroke: #46ff46; stroke-opacity: 0.9; stroke-width: 1; vector-effect: non-scaling-stroke; }
  .pt circle { fill: none; stroke: #22d3ee; stroke-width: 1.5; vector-effect: non-scaling-stroke; }
  .pt path { fill: none; stroke: #22d3ee; stroke-width: 1.5; vector-effect: non-scaling-stroke; }
  .pt.hand circle, .pt.hand path { stroke: #fde047; }
  .pt.sel circle { stroke-width: 3; }
  .label { fill: #fff; paint-order: stroke; stroke: #000; pointer-events: none; }
  canvas.loupe { position: absolute; inset: auto; border-radius: 50%; border: 3px solid #fff; box-sizing: border-box; pointer-events: none; }
  .rep { margin: 0; white-space: pre-wrap; font: 12px/1.5 ui-monospace, Menlo, monospace; color: var(--muted); }
  .chip { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 999px; padding: 0.25rem 0.8rem; font: inherit; cursor: pointer; }
  .chip.on { border-color: var(--accent); color: var(--accent); font-weight: 700; }
  .btn { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 10px; padding: 0.45rem 1rem; font: inherit; cursor: pointer; }
  .btn:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
  .btn:disabled { opacity: 0.45; cursor: default; }
</style>
