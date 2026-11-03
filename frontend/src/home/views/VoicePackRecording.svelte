<script>
  import { onDestroy } from 'svelte';
  import { t } from '../../lib/i18n.js';
  // Voice Pack → Record: the keys of a group with the text to read, record your own voice for each of them. A recording is
  // cut and faded automatically and stored as the file of the key in the folder of the pack (the next one as the next variant);
  // "Adjust" opens it in the sound editor. The recorded files are listed in the pack and are never overwritten by generating.
  import { apiJson } from '../../lib/api.js';
  import { confirmDialog } from '../../lib/confirm.js';
  import { proposeTrim } from '../../lib/soundTrim.js';
  import { canRecord, startMic } from '../../lib/micRecorder.js';
  import SoundEditor from './SoundEditor.svelte';

  let { pack = '', group = '', onpackcreated } = $props();

  const query = (extra = '') => `pack=${encodeURIComponent(pack)}${extra}`;
  const fileName = (key, index) => (index === 0 ? `${key}.mp3` : `${key}+${index}.mp3`);

  let rows = $state([]);
  let counts = $state(null);
  let loading = $state(false);
  let onlyMissing = $state(false);
  let message = $state('');
  let target = $state(null);           // { key, text, filename, quick } the file the next recording is stored as
  let phase = $state('idle');          // idle, recording, saving
  let level = $state(0);
  let seconds = $state(0);
  let editing = $state(null);          // the filename that is open in the sound editor
  let copyName = $state('');
  let mic = null;
  let playing = null;
  let token = 0;

  async function load() {
    const mine = ++token;
    loading = true;
    const body = pack && group ? await apiJson('GET', `/api/voicepack/recording?group=${encodeURIComponent(group)}&${query()}`) : { rows: [] };
    if (mine !== token) return;
    loading = false;
    if (body.error) { message = t(body.error); rows = []; return; }
    rows = body.rows;
    counts = body.counts || null;
  }
  $effect(() => { void pack; void group; target = null; load(); });

  let shown = $derived(onlyMissing ? rows.filter((r) => r.status === 'missing') : rows);
  let groupCounts = $derived(counts?.groups?.[group] || null);

  // The next key without a file after `key` (from the start when `key` is null), going round once.
  function nextMissing(key) {
    const at = key == null ? -1 : rows.findIndex((r) => r.key === key);
    return [...rows.slice(at + 1), ...rows.slice(0, at + 1)].find((r) => r.status === 'missing' && r.key !== key) || null;
  }
  let upcoming = $derived(target ? nextMissing(target.key) : null);

  function pick(row, index, quick = false) {
    if (phase !== 'idle') return;
    message = '';
    target = { key: row.key, text: row.text, filename: fileName(row.key, index), quick };
  }
  function startQuick() {
    const row = nextMissing(null) || null;
    if (!row) { message = t('Every key of this group has a file.'); return; }
    pick(row, 0, true);
  }

  async function begin() {
    if (phase !== 'idle' || !target) return;
    message = '';
    try {
      mic = await startMic({
        onlevel: (l, s) => { level = l; seconds = s; },
        onended: finish,
      });
      phase = 'recording';
    } catch (e) {
      message = e?.name === 'NotAllowedError' ? t('The microphone is not allowed. Allow it for this page in the browser.')
        : t('No microphone was found.');
    }
  }
  const end = () => mic?.stop();

  async function finish(blob) {
    mic = null;
    level = 0;
    if (!blob) { phase = 'idle'; message = t('Nothing was recorded.'); return; }
    phase = 'saving';
    const current = target;
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      let buffer;
      try { buffer = await ctx.decodeAudioData(await blob.arrayBuffer()); } finally { ctx.close(); }
      const found = proposeTrim(Array.from({ length: buffer.numberOfChannels }, (_, i) => buffer.getChannelData(i)), buffer.sampleRate);
      if (!found) { message = t('Nothing audible was recorded.'); return; }
      const q = new URLSearchParams({ pack, name: current.filename, start: found.start.toFixed(3), end: found.end.toFixed(3),
                                      fade_in: found.fadeIn.toFixed(3), fade_out: found.fadeOut.toFixed(3) });
      const res = await fetch(`/api/voicepack/recording/edit?${q}`, { method: 'POST', body: blob }).then((r) => r.json());
      if (res.error) { message = t(res.error); return; }
      await load();
      const row = current.quick ? nextMissing(current.key) : null;
      target = row ? { ...pickFields(row), quick: true } : null;
      if (current.quick && !row) message = t('Every key of this group has a file.');
    } catch (e) {
      message = t('The recording could not be saved.');
    } finally {
      phase = 'idle';
    }
  }
  const pickFields = (row) => ({ key: row.key, text: row.text, filename: fileName(row.key, 0) });

  function cancelTake() {
    if (phase === 'recording') mic?.cancel();
    mic = null;
    phase = 'idle';
    level = 0;
    target = null;
  }

  function play(filename) {
    if (playing) playing.pause();
    playing = new Audio(`/api/voicepack/file/${encodeURIComponent(filename)}?${query(`&t=${Date.now()}`)}`);
    playing.play().catch(() => { message = t('Could not play {file}.', { file: filename }); });
  }

  async function remove(row, variant) {
    if (!await confirmDialog(t('Delete {name}?', { name: variant.filename }))) return;
    const res = await apiJson('DELETE', `/api/voicepack/recording?filename=${encodeURIComponent(variant.filename)}&${query()}`);
    if (res.error) { message = t(res.error); return; }
    message = '';
    await load();
  }

  async function copyPack() {
    message = '';
    const res = await apiJson('POST', '/api/voicepack/packs/copy', { source: pack, name: copyName });
    if (res.error) { message = t(res.error); return; }
    copyName = '';
    message = t('The pack {name} was made. Pick it in the list above.', { name: res.name });
    onpackcreated?.(res.name);
  }

  const editor = $derived(editing && {
    base: '/api/voicepack/recording', extra: { pack },
    fileUrl: (f) => `/api/voicepack/file/${encodeURIComponent(f)}?${query(`&t=${Date.now()}`)}`,
  });
  async function adjusted() { editing = null; await load(); }

  function typing(e) {
    return ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target?.tagName) || e.target?.isContentEditable;
  }
  function onKeydown(e) {
    if (e.key === 'Escape' && target && !editing) { cancelTake(); return; }
    if (e.code !== 'Space' || !target || editing || typing(e)) return;
    e.preventDefault();
    if (phase === 'idle') begin();
    else if (phase === 'recording') end();
  }
  function onKeyup(e) {
    if (e.code === 'Space' && target && !editing && !typing(e)) e.preventDefault();   // a focused button would click
  }

  onDestroy(() => { mic?.cancel(); playing?.pause(); });
  const clock = (value) => `${Math.floor(value / 60)}:${String(Math.floor(value % 60)).padStart(2, '0')}`;
  const STATUS = { recorded: t('recorded'), generated: t('generated'), missing: t('missing') };
</script>

<svelte:window onkeydown={onKeydown} onkeyup={onKeyup} />

<div class="settings-section">
  <div class="settings-section-title">{t('Record your own voice')}</div>
  {#if !canRecord}
    <p class="note">{t('Recording needs https or localhost. Uploading works on any address.')}</p>
  {/if}
  {#if counts}
    <p class="note counter">
      {t('{recorded} of {total} keys recorded, {generated} generated, {missing} missing', counts)}
      {#if groupCounts}<br>{t('This group: {recorded} of {total} recorded, {missing} missing', groupCounts)}{/if}
    </p>
  {/if}

  <div class="desk" class:active={!!target}>
    {#if target}
      <div class="say">{target.text}</div>
      <div class="meta">
        <span>{target.filename}</span>
        {#if target.quick && upcoming}<span>{t('Next: {text}', { text: upcoming.text })}</span>{/if}
      </div>
      <div class="meter" role="progressbar" aria-label={t('Input level')} aria-valuemin="0" aria-valuemax="100" aria-valuenow={Math.round(level * 100)}>
        <div class="bar" class:clip={level >= 0.98} style:width="{Math.round(level * 100)}%"></div>
      </div>
      <div class="controls">
        {#if phase === 'recording'}
          <button type="button" class="act primary" onclick={end}>■ {t('Stop')}</button>
        {:else}
          <button type="button" class="act primary" disabled={phase === 'saving' || !canRecord} onclick={begin}>● {t('Record')}</button>
        {/if}
        <span class="clock">{clock(seconds)}</span>
        <span class="state">{phase === 'saving' ? t('Saving…') : phase === 'recording' ? t('Space stops') : t('Space starts')}</span>
        <span class="spacer"></span>
        <button type="button" class="act" disabled={phase === 'saving'} onclick={cancelTake}>{t('Close')}</button>
      </div>
    {:else}
      <div class="say idle">{t('Pick a key or start with the next missing one.')}</div>
      <div class="controls">
        <button type="button" class="act primary" disabled={!canRecord || !rows.length} onclick={startQuick}>● {t('Record next missing')}</button>
        <label class="filter"><input type="checkbox" bind:checked={onlyMissing}> {t('Only missing')}</label>
      </div>
    {/if}
    <div class="message">{message}</div>
  </div>

  <ul class="rows" aria-busy={loading}>
    {#each shown as row (row.key)}
      <li class:current={target?.key === row.key}>
        <div class="head">
          <span class="key">{row.key}</span>
          <span class="text">{row.text}</span>
          <span class="chip {row.status}">{STATUS[row.status]}</span>
          <button type="button" class="act" disabled={!canRecord || phase !== 'idle'} onclick={() => pick(row, row.variants.length)}>
            ● {row.variants.length ? t('Add variant') : t('Record')}
          </button>
        </div>
        {#each row.variants as variant (variant.filename)}
          <div class="variant">
            <button type="button" class="act" title={t('Listen')} onclick={() => play(variant.filename)}>▶</button>
            <span class="file">{variant.filename}</span>
            <span class="chip {variant.recorded ? 'recorded' : 'generated'}">{variant.recorded ? STATUS.recorded : STATUS.generated}</span>
            <span class="spacer"></span>
            <button type="button" class="act" disabled={!canRecord || phase !== 'idle'} onclick={() => pick(row, variant.index)}>● {t('Record again')}</button>
            <button type="button" class="act" disabled={phase !== 'idle'} onclick={() => (editing = variant.filename)}>{t('Adjust')}</button>
            <button type="button" class="act remove" title={t('Delete')} disabled={phase !== 'idle'} onclick={() => remove(row, variant)}>×</button>
          </div>
        {/each}
      </li>
    {/each}
  </ul>
  {#if !shown.length && !loading}<p class="note">{onlyMissing ? t('Every key of this group has a file.') : t('No keys in this group.')}</p>{/if}
</div>

<div class="settings-section">
  <div class="settings-section-title">{t('New pack for recordings')}</div>
  <p class="note">{t('A copy of the selected pack: the same keys and texts to read, a folder of its own for your files. Select it as the voice in Audio & Voice once it has files.')}</p>
  <div class="copy">
    <input type="text" bind:value={copyName} maxlength="32" placeholder={t('Name of the new pack')} aria-label={t('Name of the new pack')}
           onkeydown={(e) => e.key === 'Enter' && copyName.trim() && copyPack()}>
    <button type="button" class="act primary" disabled={!copyName.trim() || !pack} onclick={copyPack}>{t('Copy {pack}', { pack })}</button>
  </div>
</div>

{#if editing}
  <div class="back" role="presentation">
    <div class="dialog" role="dialog" aria-modal="true" aria-label={t('Adjust')}>
      <SoundEditor library={editing} target={editor} onsaved={adjusted} oncancel={() => (editing = null)} />
    </div>
  </div>
{/if}

<style>
  .counter { line-height: 1.5; }
  .desk {
    position: sticky; top: 0; z-index: 5; display: flex; flex-direction: column; gap: 0.5rem; min-height: 11rem;
    padding: 0.8rem 1rem; margin-bottom: 0.8rem; border-radius: 12px; background: var(--bg, #0f1115);
    border: 1px solid var(--glass-border);
  }
  .desk.active { border-color: var(--accent); }
  .say { font-size: 1.6rem; font-weight: 700; line-height: 1.25; min-height: 2rem; overflow-wrap: anywhere; }
  .say.idle { font-size: 1rem; font-weight: 400; color: var(--muted); }
  .meta { display: flex; justify-content: space-between; gap: 1rem; font-size: 0.8rem; color: var(--muted); min-height: 1.1rem; }
  .meter { height: 0.6rem; border-radius: 999px; background: rgba(0, 0, 0, 0.35); border: 1px solid var(--glass-border); overflow: hidden; }
  .bar { height: 100%; background: var(--accent); transition: width 0.05s linear; }
  .bar.clip { background: var(--red); }
  .controls { display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap; }
  .clock { font-variant-numeric: tabular-nums; }
  .state { font-size: 0.8rem; color: var(--muted); }
  .spacer { flex: 1; }
  .message { min-height: 1.2rem; font-size: 0.85rem; color: var(--yellow); }
  .filter { font-size: 0.85rem; color: var(--muted); display: inline-flex; gap: 0.3rem; align-items: center; }
  .rows { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.4rem; }
  .rows li { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 8px; padding: 0.5rem 0.7rem; }
  .rows li.current { border-color: var(--accent); }
  .head, .variant { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
  .variant { margin-top: 0.35rem; padding-left: 0.6rem; }
  .key { font-weight: 700; min-width: 4rem; }
  .text { color: var(--muted); font-size: 0.85rem; flex: 1; min-width: 6rem; overflow-wrap: anywhere; }
  .file { font-size: 0.8rem; color: var(--muted); }
  .chip { font-size: 0.7rem; border: 1px solid var(--glass-border); border-radius: 999px; padding: 0 0.5rem; color: var(--muted); }
  .chip.recorded { color: var(--green); border-color: var(--green); }
  .chip.missing { color: var(--yellow); }
  .act {
    background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 6px; color: var(--muted);
    padding: 0.25rem 0.7rem; font-family: inherit; font-size: 0.8rem; cursor: pointer;
  }
  .act:hover:not(:disabled) { border-color: var(--accent); color: var(--text); }
  .act.primary { color: var(--text); border-color: var(--accent); }
  .act.remove:hover:not(:disabled) { border-color: var(--red); color: var(--red); }
  .act:disabled { opacity: 0.45; cursor: default; }
  .copy { display: flex; gap: 0.6rem; flex-wrap: wrap; }
  .copy input {
    flex: 1; min-width: 10rem; background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); color: var(--text);
    border-radius: 6px; padding: 0.4rem 0.6rem; font-family: inherit;
  }
  .back { position: fixed; inset: 0; z-index: 1000; display: flex; align-items: center; justify-content: center; background: rgba(0, 0, 0, 0.55); }
  .dialog {
    width: min(52rem, calc(100vw - 2rem)); max-height: calc(100vh - 2rem); overflow: auto; padding: 1rem 1.2rem;
    border-radius: 12px; background: var(--bg, #0f1115); border: 1px solid var(--glass-border); box-shadow: 0 12px 40px rgba(0, 0, 0, 0.5);
  }
</style>
