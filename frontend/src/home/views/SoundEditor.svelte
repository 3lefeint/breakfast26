<script>
  // Cuts a sound: two marks on the waveform, a fade in and a fade out, a click plays from there. The server cuts the
  // part, sets it to the loudness of the library and stores the mp3 (POST /api/scenes/sounds/edit). The sound is a file
  // picked from the computer (`file`) or one of the library (`library`).
  import { onDestroy, onMount } from 'svelte';
  import { t } from '../../lib/i18n.js';
  import { confirmDialog } from '../../lib/confirm.js';
  import { proposeTrim } from '../../lib/soundTrim.js';

  let { file = null, library = '', taken = [], folder = 'scenes', suggest = '', onsaved, oncancel } = $props();
  const BASE = { scenes: '/api/scenes/sounds', achievements: '/api/admin/achievement-sounds' };

  const MAX_SECONDS = 60;
  const MIN_VIEW = 0.1;               // the smallest part of the sound the waveform can show, in seconds
  const SHAPES = [{ p: 1, label: t('Linear') }, { p: 2, label: t('Soft') }, { p: 3, label: t('Natural') }, { p: 0.5, label: t('Fast') }];
  const GRAB = 18;                  // pixels around a mark that grab it
  const FADE_Y = 8;                 // height of the fade handles on the waveform
  const FADE_GRAB = 11;             // pixels around a fade handle that grab it
  const WAVE_H = 150;
  const CURVE_GRAB = 10;
  const FINE = 0.1;                 // with Shift held a drag moves a fade by a tenth of the distance

  let canvas = $state(null);
  let width = $state(600);
  let buffer = $state(null);
  let loudest = $state(1);          // the largest sample of the whole file, the waveform is scaled by it
  let viewFrom = $state(0);         // the part of the sound on the screen, in seconds
  let viewTo = $state(1);
  let error = $state('');
  let message = $state('');
  let saving = $state(false);
  let name = $state('');
  let start = $state(0);
  let end = $state(1);
  let fadeIn = $state(0);
  let fadeOut = $state(0);
  let curveIn = $state(1);          // the power the level follows along a fade: 1 linear, above 1 starts quietly
  let curveOut = $state(1);
  let trim = $state(0);             // dB, this sound louder or quieter than the level of the library
  let lowCut = $state(false);       // the optional effects of the server, all off: a low cut, a noise reduction, a compressor
  let noise = $state('');           // '', 'light', 'medium', 'strong'
  let compress = $state('');        // '', 'light', 'strong'
  let rendering = $state(false);    // "Listen with effects" is waiting for the server
  let trimNote = $state('');
  let playing = $state(false);
  let head = $state(null);          // seconds of the play position, null when not playing

  let ctx = null;
  let source = null;
  let raf = 0;
  let began = 0;                    // context time of the play start
  let from = 0;
  let drag = null;
  let effectsAudio = null;

  let duration = $derived(buffer ? buffer.duration : 0);
  let span = $derived(viewTo - viewFrom);
  let zoomed = $derived(duration > 0 && span < duration - 0.001);
  // The waveform of the part on the screen: one bar per two pixels, so a zoomed part shows its real detail.
  let peaks = $derived.by(() => {
    if (!buffer || !width || span <= 0) return [];
    const bins = Math.max(1, Math.ceil(width / 2));
    const out = new Array(bins).fill(0);
    const first = Math.floor(viewFrom * buffer.sampleRate);
    const last = Math.min(buffer.length, Math.ceil(viewTo * buffer.sampleRate));
    const step = (last - first) / bins;
    for (let c = 0; c < buffer.numberOfChannels; c++) {
      const data = buffer.getChannelData(c);
      for (let i = 0; i < bins; i++) {
        const from = first + Math.floor(i * step), to = Math.max(from + 1, first + Math.floor((i + 1) * step));
        let top = 0;
        for (let j = from; j < Math.min(to, data.length); j++) top = Math.max(top, Math.abs(data[j]));
        out[i] = Math.max(out[i], top);
      }
    }
    return out.map((p) => Math.min(1, p / loudest));
  });
  let length = $derived(end - start);
  let tooLong = $derived(length > MAX_SECONDS);
  let maxFade = $derived(Math.max(0, Math.min(5, length)));

  function cleanName(text) {
    const stem = text.replace(/\.[^.]*$/, '').normalize('NFD').replace(/[̀-ͯ]/g, '')
      .replace(/[^A-Za-z0-9._+-]+/g, '_').replace(/^[^A-Za-z0-9]+/, '').slice(0, 59);
    return (stem || 'sound') + '.mp3';
  }

  onMount(async () => {
    name = library || suggest || cleanName(file?.name || '');
    try {
      ctx = new (window.AudioContext || window.webkitAudioContext)();
      const bytes = file ? await file.arrayBuffer() : await fetch(`/api/sound/${encodeURIComponent(library)}?t=${Date.now()}`, { cache: 'no-store' }).then((r) => r.arrayBuffer());
      buffer = await ctx.decodeAudioData(bytes);
    } catch (e) {
      error = t('This file could not be read as audio.');
      return;
    }
    end = Math.min(buffer.duration, MAX_SECONDS);
    let top = 0.001;
    for (let c = 0; c < buffer.numberOfChannels; c++) {
      const data = buffer.getChannelData(c);
      for (let j = 0; j < data.length; j++) top = Math.max(top, Math.abs(data[j]));
    }
    loudest = top;
    viewFrom = 0;
    viewTo = buffer.duration;
  });

  onDestroy(() => { stop(); effectsAudio?.pause(); try { ctx?.close(); } catch (_) { /* already closed */ } });

  // Seconds on the screen: a point (xOf), a length (px) and back (timeOf).
  const xOf = (seconds) => (span > 0 ? ((seconds - viewFrom) / span) * width : 0);
  const px = (seconds) => (span > 0 ? (seconds / span) * width : 0);
  const timeOf = (x) => Math.max(0, Math.min(duration, viewFrom + (x / width) * span));

  function zoomAt(factor, x) {
    const next = Math.max(MIN_VIEW, Math.min(duration, span / factor));
    const at = viewFrom + (x / width) * span;
    const from = Math.max(0, Math.min(duration - next, at - (x / width) * next));
    viewFrom = from;
    viewTo = from + next;
  }
  const zoomMiddle = (factor) => zoomAt(factor, width / 2);
  function setViewFrom(value) {
    const from = Math.max(0, Math.min(duration - span, Number(value) || 0));
    viewTo = from + span;
    viewFrom = from;
  }
  function showSelection() {
    const margin = Math.max(0.05, length * 0.1);
    viewFrom = Math.max(0, start - margin);
    viewTo = Math.min(duration, Math.max(end + margin, viewFrom + MIN_VIEW));
  }
  function showAll() { viewFrom = 0; viewTo = duration; }

  // Ctrl + wheel zooms around the pointer; the wheel alone moves the view while it is zoomed in.
  $effect(() => {
    const el = canvas;
    if (!el) return;
    const onWheel = (e) => {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX - el.getBoundingClientRect().left);
      } else if (zoomed) {
        e.preventDefault();
        setViewFrom(viewFrom + ((e.deltaX || e.deltaY) / width) * span);
      }
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  });

  function colour(canvasEl, name, fallback) {
    return getComputedStyle(canvasEl).getPropertyValue(name).trim() || fallback;
  }

  function draw() {
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const h = WAVE_H;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(h * dpr);
    const g = canvas.getContext('2d');
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, width, h);
    const accent = colour(canvas, '--accent', '#7aa2f7');
    const muted = colour(canvas, '--muted', '#888');
    const xs = xOf(start), xe = xOf(end);
    g.fillStyle = 'rgba(255,255,255,0.06)';
    g.fillRect(xs, 0, xe - xs, h);
    const mid = h / 2;
    for (let i = 0; i < peaks.length; i++) {
      const x = (i / peaks.length) * width;
      const inside = x + width / peaks.length >= xs && x <= xe;
      g.fillStyle = inside ? accent : muted;
      g.globalAlpha = inside ? 0.9 : 0.35;
      const half = Math.max(1, peaks[i] * (mid - 6));
      g.fillRect(x, mid - half, Math.max(1, width / peaks.length), half * 2);
    }
    g.globalAlpha = 1;
    g.strokeStyle = colour(canvas, '--text', '#fff');
    g.lineWidth = 1.5;
    g.globalAlpha = 0.85;
    g.beginPath();                                      // the fades as the line the volume follows
    const steps = 24;
    g.moveTo(xs, h - 4);
    for (let i = 1; i <= steps; i++) g.lineTo(xs + px(fadeIn) * (i / steps), h - 4 - (h - 8) * Math.pow(i / steps, curveIn));
    g.lineTo(xe - px(fadeOut), 4);
    for (let i = steps - 1; i >= 0; i--) g.lineTo(xe - px(fadeOut) * (i / steps), h - 4 - (h - 8) * Math.pow(i / steps, curveOut));
    g.stroke();
    g.globalAlpha = 1;
    g.fillStyle = 'rgba(0,0,0,0.45)';
    g.fillRect(0, 0, Math.max(0, Math.min(width, xs)), h);
    const rest = Math.max(0, Math.min(width, xe));
    g.fillRect(rest, 0, width - rest, h);
    g.fillStyle = accent;
    g.fillRect(xs - 1.5, 0, 3, h);
    g.fillRect(xe - 1.5, 0, 3, h);
    for (const [x, dir] of [[xs, 1], [xe, -1]]) {         // a grip on each mark, to see that it can be dragged
      g.fillRect(dir < 0 ? x - 12 : x, h - 22, 12, 22);
      g.fillStyle = 'rgba(0,0,0,0.6)';
      g.fillRect((dir < 0 ? x - 12 : x) + 4, h - 17, 1.5, 12);
      g.fillRect((dir < 0 ? x - 12 : x) + 7, h - 17, 1.5, 12);
      g.fillStyle = accent;
    }
    g.fillStyle = colour(canvas, '--text', '#fff');       // a handle at the end of each fade, drag it to set the length
    for (const x of [xs + px(fadeIn), xe - px(fadeOut)]) {
      g.beginPath();
      g.arc(x, FADE_Y, 6, 0, Math.PI * 2);
      g.fill();
      g.strokeStyle = accent;
      g.lineWidth = 2;
      g.stroke();
    }
    g.fillStyle = accent;                                  // a handle in the middle of each fade, drag it up or down to bend it
    for (const side of ['in', 'out']) {
      const at = curveHandle(side);
      if (!at) continue;
      g.beginPath();
      g.arc(at.x, at.y, 5, 0, Math.PI * 2);
      g.fill();
      g.strokeStyle = colour(canvas, '--text', '#fff');
      g.lineWidth = 1.5;
      g.stroke();
    }
    if (head != null) {
      g.fillStyle = colour(canvas, '--text', '#fff');
      g.fillRect(xOf(head) - 0.5, 0, 1.5, h);
    }
  }

  $effect(() => { draw(); });

  function setStart(value) { start = Math.max(0, Math.min(Number(value) || 0, end - 0.05)); fitFades(); }
  function setEnd(value) { end = Math.min(duration, Math.max(Number(value) || 0, start + 0.05)); fitFades(); }
  function fitFades() {
    fadeIn = Math.min(fadeIn, length);
    fadeOut = Math.min(fadeOut, Math.max(0, length - fadeIn));
  }
  const setFadeIn = (value) => { fadeIn = Math.min(Number(value) || 0, length - fadeOut); };
  const setFadeOut = (value) => { fadeOut = Math.min(Number(value) || 0, length - fadeIn); };

  function point(e) {
    const rect = canvas.getBoundingClientRect();
    return e.clientX - rect.left;
  }

  // Where the handle of a fade's curve sits: on the line, halfway along the fade.
  function curveHandle(side) {
    const fade = side === 'in' ? fadeIn : fadeOut;
    const p = side === 'in' ? curveIn : curveOut;
    const x = side === 'in' ? xOf(start + fade / 2) : xOf(end - fade / 2);
    return { x, y: WAVE_H - 4 - (WAVE_H - 8) * Math.pow(0.5, p) };
  }

  function curveHandleAt(e) {
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left, y = e.clientY - rect.top;
    for (const side of ['in', 'out']) {
      const at = curveHandle(side);
      if (at && Math.hypot(x - at.x, y - at.y) <= CURVE_GRAB) return side === 'in' ? 'curveIn' : 'curveOut';
    }
    return null;
  }

  const PRESET_POWERS = SHAPES.map((s) => s.p);

  function dragCurve(e) {
    const side = drag.kind === 'curveIn' ? 'in' : 'out';
    const y = e.clientY - canvas.getBoundingClientRect().top;
    if (e.shiftKey !== drag.fine) {                     // Shift pressed or released: carry on from where the handle is
      drag.fine = e.shiftKey;
      drag.y0 = y;
      drag.l0 = Math.pow(0.5, side === 'in' ? curveIn : curveOut);
    }
    const level = drag.l0 + ((drag.y0 - y) / (WAVE_H - 8)) * (e.shiftKey ? FINE : 1);
    let p = Math.log(Math.min(0.99, Math.max(0.01, level))) / Math.log(0.5);
    p = Math.min(4, Math.max(0.25, p));
    if (!e.shiftKey) {                                  // snaps to a preset that is close
      const near = PRESET_POWERS.find((q) => Math.abs(Math.log(p / q)) < 0.06);
      if (near) p = near;
    }
    p = Math.round(p * 100) / 100;
    if (side === 'in') curveIn = p; else curveOut = p;
  }

  function fadeHandleAt(e) {
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left, y = e.clientY - rect.top;
    const near = (hx) => Math.hypot(x - hx, y - FADE_Y) <= FADE_GRAB;
    const nearIn = near(xOf(start + fadeIn)), nearOut = near(xOf(end - fadeOut));
    if (nearIn && nearOut) return Math.abs(x - xOf(start + fadeIn)) <= Math.abs(x - xOf(end - fadeOut)) ? 'fadeIn' : 'fadeOut';
    return nearIn ? 'fadeIn' : nearOut ? 'fadeOut' : null;
  }

  function dragFade(e) {
    const side = drag.kind === 'fadeIn' ? 1 : -1;
    const shift = e.shiftKey;
    const x = point(e);
    if (shift !== drag.fine) {                          // Shift pressed or released: carry on from where the handle is
      drag.fine = shift;
      drag.x0 = x;
      drag.v0 = side > 0 ? fadeIn : fadeOut;
    }
    const seconds = ((x - drag.x0) / width) * span * (shift ? FINE : 1);
    const value = Math.max(0, Math.min(maxFade, drag.v0 + side * seconds));
    if (side > 0) setFadeIn(value); else setFadeOut(value);
  }

  function down(e) {
    if (!buffer) return;
    const bend = curveHandleAt(e);
    if (bend) {
      const y = e.clientY - canvas.getBoundingClientRect().top;
      drag = { kind: bend, fine: false, y0: y, l0: Math.pow(0.5, bend === 'curveIn' ? curveIn : curveOut) };
      canvas.setPointerCapture(e.pointerId);
      return;
    }
    const handle = fadeHandleAt(e);
    if (handle) {
      drag = { kind: handle, fine: false, x0: point(e), v0: handle === 'fadeIn' ? fadeIn : fadeOut };
      canvas.setPointerCapture(e.pointerId);
      return;
    }
    const x = point(e);
    const ds = Math.abs(x - xOf(start)), de = Math.abs(x - xOf(end));
    if (Math.min(ds, de) <= GRAB) {
      drag = { kind: ds <= de ? 'start' : 'end' };
      canvas.setPointerCapture(e.pointerId);
    } else {                                             // a click plays, a drag moves the view
      drag = { kind: 'canvas', x0: x, from0: viewFrom, moved: false, at: timeOf(x) };
      canvas.setPointerCapture(e.pointerId);
    }
  }

  function move(e) {
    if (!drag) {
      const x = point(e);
      canvas.style.cursor = curveHandleAt(e) ? 'ns-resize' : fadeHandleAt(e) ? 'ew-resize'
        : Math.min(Math.abs(x - xOf(start)), Math.abs(x - xOf(end))) <= GRAB ? 'col-resize' : 'crosshair';
      return;
    }
    if (drag.kind === 'canvas') {
      const x = point(e);
      if (Math.abs(x - drag.x0) > 3) drag.moved = true;
      if (drag.moved && zoomed) setViewFrom(drag.from0 - ((x - drag.x0) / width) * span);
      canvas.style.cursor = drag.moved && zoomed ? 'grabbing' : 'crosshair';
      return;
    }
    if (drag.kind === 'fadeIn' || drag.kind === 'fadeOut') { dragFade(e); return; }
    if (drag.kind === 'curveIn' || drag.kind === 'curveOut') { dragCurve(e); return; }
    const at = timeOf(point(e));
    if (drag.kind === 'start') setStart(at); else setEnd(at);
  }

  // A click inside the selection plays from there, a click outside it plays the whole cut, fades included.
  function up() {
    if (drag?.kind === 'canvas' && !drag.moved) {
      if (drag.at >= start && drag.at < end) play(drag.at);
      else play(start);
    }
    drag = null;
  }

  // The space bar starts and stops the cut, as in an audio editor, unless a field that takes text has the focus.
  function onKey(e) {
    if (e.code !== 'Space' || e.repeat || !buffer) return;
    const field = document.activeElement;
    const typing = field && (field.tagName === 'TEXTAREA' || field.tagName === 'SELECT'
      || (field.tagName === 'INPUT' && !['range', 'checkbox'].includes(field.type)));
    if (typing) return;
    e.preventDefault();
    if (field?.tagName === 'BUTTON') field.blur();      // a focused button would take the space as a click
    if (playing) stop(); else play(start);
  }

  // Auto trim: the marks go to the first and the last point above about -40 dB with a little room, and short fades are
  // proposed. It is only a proposal, everything can be changed afterwards and the button can propose again.
  function autoTrim() {
    trimNote = '';
    const channels = Array.from({ length: buffer.numberOfChannels }, (_, c) => buffer.getChannelData(c));
    const found = proposeTrim(channels, buffer.sampleRate);
    if (!found) { trimNote = t('Nothing in this sound is louder than -40 dB.'); return; }
    start = found.start;
    end = Math.min(found.end, start + MAX_SECONDS);
    fadeIn = found.fadeIn;
    fadeOut = found.fadeOut;
    fitFades();
    showSelection();
  }

  function query(extra = {}) {
    const q = new URLSearchParams({ start: start.toFixed(3), end: end.toFixed(3), fade_in: fadeIn.toFixed(3), fade_out: fadeOut.toFixed(3),
                                    trim: String(trim), curve_in: String(curveIn), curve_out: String(curveOut),
                                    low_cut: String(lowCut), noise, compress, ...extra });
    if (!file) q.set('source', library);
    return q;
  }

  // The browser cannot play the filters of ffmpeg, so the server renders the first seconds of the selection with the
  // effects (and the level of the library) and this plays the result.
  async function listenWithEffects() {
    message = '';
    stop();
    effectsAudio?.pause();
    rendering = true;
    try {
      const res = await fetch(`${BASE[folder]}/preview?${query()}`, { method: 'POST', body: file || undefined });
      if ((res.headers.get('content-type') || '').includes('json')) {
        message = t((await res.json()).error || 'The preview failed.');
      } else {
        const url = URL.createObjectURL(await res.blob());
        effectsAudio = new Audio(url);
        effectsAudio.onended = () => URL.revokeObjectURL(url);
        await effectsAudio.play();
      }
    } catch (e) {
      message = t('The preview failed.');
    } finally {
      rendering = false;
    }
  }

  function stop() {
    effectsAudio?.pause();
    cancelAnimationFrame(raf);
    if (source) {
      source.onended = null;
      try { source.stop(); } catch (_) { /* never started */ }
      source = null;
    }
    playing = false;
    head = null;
  }

  function play(at = start) {
    if (!buffer || !ctx) return;
    stop();
    ctx.resume?.();
    from = at;
    const span = end - at;
    if (span <= 0) return;
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    const gain = ctx.createGain();
    const steps = 256;
    const curve = new Float32Array(steps);
    for (let i = 0; i < steps; i++) {                   // the fades, heard as they will be saved
      const pos = at + (span * i) / (steps - 1);
      const rise = fadeIn > 0 ? Math.min(1, Math.max(0, (pos - start) / fadeIn)) ** curveIn : 1;
      const fall = fadeOut > 0 ? Math.min(1, Math.max(0, (end - pos) / fadeOut)) ** curveOut : 1;
      curve[i] = Math.min(rise, fall);
    }
    gain.gain.setValueCurveAtTime(curve, ctx.currentTime, span);
    src.connect(gain);
    gain.connect(ctx.destination);
    began = ctx.currentTime;
    src.onended = () => { if (source === src) stop(); };
    src.start(0, at, span);
    source = src;
    playing = true;
    const tick = () => {
      if (!playing) return;
      head = from + (ctx.currentTime - began);
      raf = requestAnimationFrame(tick);
    };
    tick();
  }

  async function save() {
    message = '';
    if (!/^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}\.mp3$/.test(name)) {
      message = t('The name must be letters, digits and . _ + - and end in .mp3.');
      return;
    }
    const replace = name === library;
    if (replace && !await confirmDialog(t('Replace {name} with the edited sound?', { name }))) return;
    if (!replace && taken.includes(name)) { message = t('A sound with this name exists already.'); return; }
    saving = true;
    try {
      const res = await fetch(`${BASE[folder]}/edit?${query({ name, overwrite: replace ? 'true' : 'false' })}`,
                              { method: 'POST', body: file || undefined }).then((r) => r.json());
      if (res.error) { message = t(res.error); return; }
      stop();
      onsaved?.(res.file);
    } catch (e) {
      message = t('The upload failed.');
    } finally {
      saving = false;
    }
  }

  const seconds = (value) => value.toFixed(2);
</script>

<svelte:window onkeydown={onKey} />

<div class="editor">
  {#if error}
    <div class="message">{error}</div>
    <div class="row"><button type="button" class="act" onclick={oncancel}>{t('Cancel')}</button></div>
  {:else if !buffer}
    <div class="note">{t('Loading…')}</div>
  {:else}
    <div class="row">
      <label class="grow">{t('Name')}
        <input type="text" bind:value={name} maxlength="64">
      </label>
      <span class="note">{t('Length {seconds} s', { seconds: seconds(duration) })}</span>
    </div>

    <div class="wave" bind:clientWidth={width}>
      <canvas bind:this={canvas} style:width="{width}px" style:height="{WAVE_H}px"
              onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={up}></canvas>
    </div>
    <div class="zoom-row">
      <button type="button" class="chip" onclick={() => zoomMiddle(1 / 1.5)} disabled={!zoomed} aria-label={t('Zoom out')}>−</button>
      <button type="button" class="chip" onclick={() => zoomMiddle(1.5)} disabled={span <= MIN_VIEW + 0.001} aria-label={t('Zoom in')}>+</button>
      <button type="button" class="chip" onclick={showSelection}>{t('Selection')}</button>
      <button type="button" class="chip" onclick={showAll} disabled={!zoomed}>{t('All')}</button>
      {#if zoomed}
        <input type="range" class="pan" min="0" max={duration - span} step="0.001" value={viewFrom}
               oninput={(e) => setViewFrom(e.target.value)} aria-label={t('Position')}>
      {/if}
      <span class="note">{t('{seconds} s on the screen', { seconds: seconds(span) })}</span>
    </div>
    <div class="note">{t('Drag the two marks to cut, the white handles to set the length of the fades and the colored ones to bend them; hold Shift for fine steps. Click inside the selection to play from there, outside it to play the cut; drag the waveform to move a zoomed view; the space bar starts and stops. Ctrl + wheel zooms.')}</div>

    <div class="row">
      <label>{t('Start')} <input type="number" min="0" max={duration} step="0.01" value={seconds(start)} onchange={(e) => setStart(e.target.value)}> s</label>
      <label>{t('End')} <input type="number" min="0" max={duration} step="0.01" value={seconds(end)} onchange={(e) => setEnd(e.target.value)}> s</label>
      <span class="note" class:warn={tooLong}>{t('Selection {seconds} s', { seconds: seconds(length) })}</span>
      <button type="button" class="act" onclick={autoTrim}>{t('Auto trim')}</button>
      {#if trimNote}<span class="note warn">{trimNote}</span>{/if}
    </div>
    {#each [['in', t('Fade in')], ['out', t('Fade out')]] as [side, label]}
      {@const curve = side === 'in' ? curveIn : curveOut}
      <div class="row">
        <label>{label}
          <input type="range" min="0" max={maxFade} step="0.05" value={side === 'in' ? fadeIn : fadeOut}
                 oninput={(e) => (side === 'in' ? setFadeIn(e.target.value) : setFadeOut(e.target.value))}>
          <input type="number" min="0" max={maxFade} step="0.01"
                 value={(side === 'in' ? fadeIn : fadeOut).toFixed(2)}
                 onchange={(e) => (side === 'in' ? setFadeIn(e.target.value) : setFadeOut(e.target.value))}> s
        </label>
        <span class="shapes">
          {#each SHAPES as shape}
            <button type="button" class="chip" class:active={Math.abs(curve - shape.p) < 0.02}
                    onclick={() => (side === 'in' ? (curveIn = shape.p) : (curveOut = shape.p))}>{shape.label}</button>
          {/each}
        </span>
        <label>{t('Curve')}
          <input type="range" min="-1" max="1" step="0.05" value={Math.log(curve) / Math.log(4)}
                 oninput={(e) => { const p = Math.round(4 ** Number(e.target.value) * 100) / 100; if (side === 'in') curveIn = p; else curveOut = p; }}>
        </label>
      </div>
    {/each}

    <div class="row">
      <label>{t('Sound level')}
        <input type="range" min="-6" max="6" step="0.5" bind:value={trim}>
        <span class="value">{trim > 0 ? '+' : ''}{Number(trim).toFixed(1)} dB</span>
      </label>
      <span class="note">{t('0 is the level of all sounds. Change it only for a sound that stays too quiet or too loud.')}</span>
    </div>

    <div class="row">
      <label class="check"><input type="checkbox" bind:checked={lowCut}> {t('Low cut')}</label>
      <label>{t('Noise reduction')}
        <select bind:value={noise}>
          <option value="">{t('Off')}</option><option value="light">{t('Light')}</option>
          <option value="medium">{t('Medium')}</option><option value="strong">{t('Strong')}</option>
        </select>
      </label>
      <label>{t('Compressor')}
        <select bind:value={compress}>
          <option value="">{t('Off')}</option><option value="light">{t('Light')}</option><option value="strong">{t('Strong')}</option>
        </select>
      </label>
      <button type="button" class="act" onclick={listenWithEffects} disabled={rendering || tooLong}>▶ {t('Listen with effects')}</button>
    </div>
    <div class="note">{t('The effects change the saved sound: first the low cut, then the noise reduction and the compressor, then the level is set. The waveform and Play selection show the sound as it is; Listen with effects plays the first seconds of the selection as they will be saved.')}</div>

    {#if tooLong}<div class="message">{t('The selection is longer than {n} seconds.', { n: MAX_SECONDS })}</div>{/if}
    {#if message}<div class="message">{message}</div>{/if}
    <div class="row">
      {#if playing}
        <button type="button" class="act" onclick={stop}>■ {t('Stop')}</button>
      {:else}
        <button type="button" class="act" onclick={() => play(start)}>▶ {t('Play selection')}</button>
      {/if}
      <span class="spacer"></span>
      <span class="note">{t('The loudness is set to the same level when saving.')}</span>
      <button type="button" class="act" onclick={oncancel}>{t('Cancel')}</button>
      <button type="button" class="act primary" onclick={save} disabled={saving || tooLong}>
        {saving ? t('Saving…') : t('Save')}
      </button>
    </div>
  {/if}
</div>

<style>
  .editor { display: flex; flex-direction: column; gap: 0.7rem; }
  .row { display: flex; align-items: center; gap: 0.8rem; flex-wrap: wrap; }
  .grow { flex: 1 1 14rem; }
  .spacer { flex: 1; }
  label { display: flex; align-items: center; gap: 0.4rem; font-size: 0.82rem; color: var(--muted); }
  .grow input { flex: 1; }
  .shapes { display: inline-flex; gap: 0.3rem; }
  .chip {
    background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 999px; color: var(--muted);
    padding: 0.1rem 0.6rem; font-family: inherit; font-size: 0.75rem; cursor: pointer;
  }
  .chip.active { border-color: var(--accent); color: var(--text); }
  .check { cursor: pointer; }
  .value { min-width: 3.2rem; color: var(--text); font-variant-numeric: tabular-nums; }
  .note { font-size: 0.78rem; color: var(--muted); }
  .note.warn, .message { color: var(--yellow); }
  .message { font-size: 0.85rem; }
  .wave { width: 100%; touch-action: none; }
  .zoom-row { display: flex; align-items: center; gap: 0.4rem; margin: 0.35rem 0; }
  .zoom-row .pan { flex: 1; min-width: 6rem; }
  canvas { display: block; background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 8px; cursor: crosshair; }
  input[type="text"], input[type="number"] {
    background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 6px; color: var(--text);
    padding: 0.35rem 0.55rem; font-family: inherit; font-size: 0.85rem;
  }
  input[type="number"] { width: 5.5rem; }
  .act {
    background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 6px; color: var(--muted);
    padding: 0.25rem 0.75rem; font-family: inherit; font-size: 0.8rem; cursor: pointer;
  }
  .act:hover:not(:disabled) { border-color: var(--accent); color: var(--text); }
  .act.primary { color: var(--text); border-color: var(--accent); }
  .act:disabled { opacity: 0.45; cursor: default; }
</style>
