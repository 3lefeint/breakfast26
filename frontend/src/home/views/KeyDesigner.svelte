<script>
  import { t } from '../../lib/i18n.js';
  // The design of one Stream Deck key: image and text layers placed on the key with the mouse (the dots on the
  // preview), a frame, and the background color. The preview is drawn by Breakfast itself, so it is what the device shows.
  import { onDestroy } from 'svelte';

  let { entry, images, symbols, symbolLabel, valueTokens, onchange, onclose } = $props();

  const STEPS = 12;
  const clone = (d) => JSON.parse(JSON.stringify(d));
  let design = $state(clone(entry.design || { layers: [], border: { color: '#ffffff', width: 0 } }));
  let selected = $state(design.layers.length ? 0 : -1);
  let snap = $state(true);
  let previewUrl = $state('');
  let previewTimer = null;
  let saveTimer = null;
  let box;

  const round = (v) => Math.round(v * 10000) / 10000;
  const layer = $derived(selected >= 0 ? design.layers[selected] : null);

  async function drawPreview() {
    try {
      const res = await fetch('/api/streamdeck/preview', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...entry, design: clone(design) }),
      });
      if (!res.ok) return;
      const url = URL.createObjectURL(await res.blob());
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      previewUrl = url;
    } catch (e) { /* the next change draws it again */ }
  }
  function changed(saveNow = true) {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(drawPreview, 120);
    if (saveNow) { clearTimeout(saveTimer); saveTimer = setTimeout(() => onchange(clone(design)), 350); }
  }
  $effect(() => { entry.color; entry.label; drawPreview(); });
  onDestroy(() => { clearTimeout(previewTimer); clearTimeout(saveTimer); if (previewUrl) URL.revokeObjectURL(previewUrl); });

  function addText() {
    design.layers.push({ kind: 'text', text: entry.label || 'Text', x: 0.5, y: 0.5, size: 0.25, color: 'auto' });
    selected = design.layers.length - 1;
    changed();
  }
  function addImage() {
    const image = entry.image || (symbols[0] ? 'symbol:' + symbols[0] : '');
    if (!image) return;
    design.layers.push({ kind: 'image', image, x: 0.5, y: 0.5, size: 0.6 });
    selected = design.layers.length - 1;
    changed();
  }
  function removeLayer() {
    design.layers.splice(selected, 1);
    selected = Math.min(selected, design.layers.length - 1);
    changed();
  }
  function move(by) {
    const to = selected + by;
    if (to < 0 || to >= design.layers.length) return;
    const [l] = design.layers.splice(selected, 1);
    design.layers.splice(to, 0, l);
    selected = to;
    changed();
  }
  // Start from how the key is drawn without a design: the picture and the label.
  function fromPlain() {
    design.layers = [];
    if (entry.image) design.layers.push({ kind: 'image', image: entry.image, x: 0.5, y: entry.label ? 0.4 : 0.5, size: entry.label ? 0.55 : 0.75 });
    if (entry.label) design.layers.push({ kind: 'text', text: entry.label, x: 0.5, y: entry.image ? 0.8 : 0.5, size: entry.image ? 0.2 : 0.28, color: 'auto' });
    selected = design.layers.length ? 0 : -1;
    changed();
  }

  // ---- dragging ----
  let dragging = -1;
  function down(e, i) {
    dragging = i;
    selected = i;
    e.currentTarget.setPointerCapture(e.pointerId);
  }
  function drag(e) {
    if (dragging < 0) return;
    const r = box.getBoundingClientRect();
    let x = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    let y = Math.min(1, Math.max(0, (e.clientY - r.top) / r.height));
    if (snap) { x = Math.round(x * STEPS) / STEPS; y = Math.round(y * STEPS) / STEPS; }
    design.layers[dragging].x = round(x);
    design.layers[dragging].y = round(y);
    changed(false);
  }
  function up() {
    if (dragging >= 0) { dragging = -1; changed(); }
  }

  const percent = (v) => Math.round(v * 100);
  const setPercent = (key) => (e) => { layer[key] = round(Math.min(1, Math.max(0, Number(e.currentTarget.value) / 100))); changed(); };
  const setSize = (e) => { layer.size = round(Number(e.currentTarget.value) / 100); changed(); };
  const layerName = (l) => (l.kind === 'text' ? `${t('Text')}: ${l.text || '…'}` : `${t('Image')}: ${l.image.replace('symbol:', '')}`);
  const setBorder = () => changed();
</script>

<div class="designer">
  <div class="top">
    <div class="editor-title">{t('Design')}</div>
    <button type="button" class="act" onclick={onclose}>{t('Done')}</button>
  </div>

  <div class="stage">
    <div class="preview" bind:this={box} onpointermove={drag} onpointerup={up} role="presentation">
      {#if previewUrl}<img src={previewUrl} alt="" draggable="false">{/if}
      {#if snap}
        <div class="raster" style="background-size: calc(100% / {STEPS}) calc(100% / {STEPS});"></div>
      {/if}
      {#each design.layers as l, i (i)}
        <button type="button" class="dot" class:sel={i === selected} style="left: {l.x * 100}%; top: {l.y * 100}%;"
                onpointerdown={(e) => down(e, i)} aria-label={layerName(l)}></button>
      {/each}
    </div>

    <div class="side">
      <div class="buttons">
        <button type="button" class="act" onclick={addText}>{t('Add text')}</button>
        <button type="button" class="act" onclick={addImage}>{t('Add image')}</button>
        <button type="button" class="act" onclick={fromPlain}>{t('From the plain layout')}</button>
      </div>
      <label class="check"><input type="checkbox" bind:checked={snap}> {t('Snap to the grid')}</label>
      <ul class="layers">
        {#each design.layers as l, i (i)}
          <li class:sel={i === selected}><button type="button" onclick={() => (selected = i)}>{layerName(l)}</button></li>
        {/each}
        {#if !design.layers.length}<li class="none">{t('No layers yet.')}</li>{/if}
      </ul>
    </div>
  </div>

  {#if layer}
    <div class="props">
      {#if layer.kind === 'text'}
        <label class="field"><span>{t('Text')}</span><input type="text" maxlength="60" bind:value={layer.text} oninput={() => changed()}></label>
        <p class="hint">{t('Values of the game: {tokens}', { tokens: valueTokens.map((v) => '{' + v + '}').join(' ') })}</p>
        <div class="field">
          <span>{t('Color')}</span>
          <label class="check"><input type="checkbox" checked={layer.color === 'auto'} onchange={(e) => { layer.color = e.currentTarget.checked ? 'auto' : '#ffffff'; changed(); }}> {t('Automatic')}</label>
          {#if layer.color !== 'auto'}<input type="color" bind:value={layer.color} onchange={() => changed()}>{/if}
        </div>
      {:else}
        <label class="field"><span>{t('Image')}</span>
          <select bind:value={layer.image} onchange={() => changed()}>
            <optgroup label={t('Symbols')}>
              {#each symbols as sym (sym)}<option value={'symbol:' + sym}>{symbolLabel[sym] || sym}</option>{/each}
            </optgroup>
            {#if images.length}
              <optgroup label={t('Your images')}>{#each images as f (f)}<option value={f}>{f}</option>{/each}</optgroup>
            {/if}
          </select>
        </label>
      {/if}
      <label class="field"><span>{t('Size')}</span>
        <input type="range" min="5" max={layer.kind === 'image' ? 200 : 100} value={percent(layer.size)} oninput={setSize}>
        <span class="val">{percent(layer.size)} %</span>
      </label>
      <div class="field">
        <span>{t('Position')}</span>
        <input type="number" min="0" max="100" value={percent(layer.x)} onchange={setPercent('x')} aria-label="X">
        <input type="number" min="0" max="100" value={percent(layer.y)} onchange={setPercent('y')} aria-label="Y">
        <span class="val">% {t('from left and top')}</span>
      </div>
      <div class="buttons">
        <button type="button" class="act" onclick={() => move(1)}>{t('Forward')}</button>
        <button type="button" class="act" onclick={() => move(-1)}>{t('Backward')}</button>
        <button type="button" class="act danger" onclick={removeLayer}>{t('Remove layer')}</button>
      </div>
    </div>
  {/if}

  <div class="props">
    <div class="field">
      <span>{t('Frame')}</span>
      <input type="range" min="0" max="24" bind:value={design.border.width} oninput={setBorder}>
      <input type="color" bind:value={design.border.color} onchange={setBorder} aria-label={t('Frame color')}>
    </div>
  </div>
</div>

<style>
  .designer { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 8px; padding: 0.75rem 0.9rem; margin: 0.75rem 0; }
  .top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; }
  .editor-title { font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; }
  .stage { display: flex; gap: 1rem; flex-wrap: wrap; }
  .preview { position: relative; width: 216px; height: 216px; flex: none; border: 1px solid var(--glass-border); touch-action: none; user-select: none; }
  .preview img { width: 100%; height: 100%; display: block; image-rendering: pixelated; }
  .raster {
    position: absolute; inset: 0; pointer-events: none;
    background-image: linear-gradient(to right, rgba(255, 255, 255, 0.18) 1px, transparent 1px), linear-gradient(to bottom, rgba(255, 255, 255, 0.18) 1px, transparent 1px);
  }
  .dot {
    position: absolute; width: 18px; height: 18px; margin: -9px 0 0 -9px; border-radius: 50%; padding: 0; cursor: grab;
    background: rgba(255, 255, 255, 0.35); border: 2px solid #fff; box-shadow: 0 0 0 1px #000;
  }
  .dot.sel { background: var(--accent); }
  .side { flex: 1; min-width: 12rem; }
  .buttons { display: flex; gap: 0.4rem; flex-wrap: wrap; margin-bottom: 0.5rem; }
  .check { display: flex; align-items: center; gap: 0.4rem; font-size: 0.85rem; color: var(--text); margin-bottom: 0.4rem; }
  .layers { list-style: none; padding: 0; margin: 0; }
  .layers li button { width: 100%; text-align: left; background: none; border: none; color: var(--muted); font-family: inherit; font-size: 0.85rem; padding: 0.25rem 0.4rem; cursor: pointer; border-radius: 4px; }
  .layers li.sel button { background: rgba(255, 255, 255, 0.1); color: var(--text); }
  .none { color: var(--muted); font-size: 0.8rem; }
  .props { margin-top: 0.7rem; }
  .field { display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.5rem; font-size: 0.9rem; color: var(--muted); flex-wrap: wrap; }
  .field > span:first-child { min-width: 5rem; }
  .field input[type="text"], .field select { flex: 1; min-width: 8rem; background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 6px; color: var(--text); padding: 0.35rem 0.55rem; font-family: inherit; font-size: 0.85rem; }
  .field input[type="number"] { width: 4.5rem; background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 6px; color: var(--text); padding: 0.35rem 0.55rem; font-family: inherit; font-size: 0.85rem; }
  .field input[type="range"] { flex: 0 1 12rem; accent-color: var(--accent); }
  input[type="color"] { width: 2.6rem; height: 1.8rem; padding: 0; border: 1px solid var(--glass-border); border-radius: 6px; background: none; }
  .val { font-size: 0.8rem; }
  .hint { color: var(--muted); font-size: 0.78rem; margin: 0 0 0.5rem; }
  .act { background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 6px; color: var(--muted); padding: 0.25rem 0.8rem; font-family: inherit; font-size: 0.8rem; cursor: pointer; }
  .act:hover { border-color: var(--accent); color: var(--text); }
  .act.danger:hover { border-color: var(--red); color: var(--red); }
</style>
