<script>
  // Settings → Audio & Voice → Sounds: the sound library the scenes play from. A file is uploaded through the editor,
  // which cuts it, sets the fades and brings it to the loudness of the library; a file of the library can be edited
  // again, renamed and deleted.
  import { onMount } from 'svelte';
  import { t } from '../../lib/i18n.js';
  import { confirmDialog } from '../../lib/confirm.js';
  import { apiJson } from '../../lib/api.js';
  import SoundEditor from './SoundEditor.svelte';
  import SoundRecorder from './SoundRecorder.svelte';

  const FOLDERS = { scenes: t('Scenes'), achievements: t('Achievements') };
  const BASE = { scenes: '/api/scenes/sounds', achievements: '/api/admin/achievement-sounds' };

  let folder = $state('scenes');
  let data = $state(null);
  let error = $state('');
  let message = $state('');
  let editing = $state(null);          // { file } for an upload, { library } for a file of the library
  let renaming = $state(null);
  let newName = $state('');
  let playing = null;
  let recording = $state(false);       // the recorder dialog is open

  // The browser allows the microphone only on https or on localhost, so on a plain http address the button stays off.
  const canRecord = typeof window !== 'undefined' && window.isSecureContext && !!navigator.mediaDevices?.getUserMedia
    && typeof MediaRecorder !== 'undefined';

  let sounds = $state([]);

  async function load() {
    try {
      const mine = folder;
      const body = await apiJson('GET', mine === 'scenes' ? '/api/scenes' : BASE.achievements);
      if (mine !== folder) return;
      if (body.error) { error = body.error.startsWith('locked') ? t('Unlock the Dev tab first.') : t(body.error); data = null; return; }
      if (mine === 'scenes' && !body.available) { error = t('Sounds are not available.'); return; }
      sounds = mine === 'scenes' ? body.sounds
        : body.file_details.map((f) => ({ ...f, used_by: f.used_by.map((u) => u.names?.en || u.id) }));
      data = body;
      error = '';
    } catch (e) {
      error = t('Could not load the sounds.');
    }
  }

  onMount(load);

  function show(next) {
    if (next === folder) return;
    folder = next;
    editing = null;
    renaming = null;
    message = '';
    data = null;
    load();
  }

  function pick(event) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    message = '';
    editing = { file };
  }

  function recorded(file) {
    recording = false;
    message = '';
    editing = { file };
  }

  async function saved(file) {
    editing = null;
    message = t('Saved {file}.', { file });
    await load();
  }

  function preview(file) {
    if (playing) playing.pause();
    playing = new Audio(`/api/sound/${encodeURIComponent(file)}?t=${Date.now()}`);
    playing.play().catch(() => { message = t('Could not play {file}.', { file }); });
  }

  async function removeFile(f) {
    const users = f.used_by.join(', ');
    const warning = !users ? '' : '\n\n' + (folder === 'scenes' ? t('It is played by: {users}. Those steps play nothing then.', { users })
      : t('It is assigned to: {users}. It is taken out there.', { users }));
    if (!await confirmDialog(t('Delete {name}?', { name: f.name }) + warning)) return;
    const res = await apiJson('DELETE', folder === 'scenes' ? `${BASE.scenes}/${encodeURIComponent(f.name)}` : `${BASE.achievements}/files/${encodeURIComponent(f.name)}`);
    if (res.error) { message = t(res.error); return; }
    message = '';
    await load();
  }

  function startRename(f) { renaming = f.name; newName = f.name; }

  async function rename(f) {
    const res = folder === 'scenes'
      ? await apiJson('POST', `${BASE.scenes}/${encodeURIComponent(f.name)}/rename`, { name: newName.trim() })
      : await apiJson('PATCH', `${BASE.achievements}/files/${encodeURIComponent(f.name)}`, { name: newName.trim() });
    if (res.error) { message = t(res.error); return; }
    renaming = null;
    message = '';
    await load();
  }

  const size = (bytes) => (bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(bytes < 10240 ? 1 : 0)} KB`);
</script>

<div class="folders">
  {#each Object.entries(FOLDERS) as [id, label]}
    <button type="button" class="tab-chip" class:active={folder === id} onclick={() => show(id)}>{label}</button>
  {/each}
</div>

{#if error}
  <div class="empty">{error}</div>
{:else if !data}
  <div class="empty">{t('Loading…')}</div>
{:else}
  {#if message}<div class="message">{message}</div>{/if}

  {#if editing}
    <div class="box">
      <div class="box-head">
        <span class="box-title">{editing.file ? editing.file.name : editing.library}</span>
      </div>
      <SoundEditor file={editing.file} library={editing.library} {folder} taken={sounds.map((s) => s.name)}
                   onsaved={saved} oncancel={() => { editing = null; }} />
    </div>
  {:else}
    <div class="box">
      <div class="box-head">
        <span class="box-title">{t('Sound library')}</span>
        <span class="actions">
          <button type="button" class="act" disabled={!canRecord} onclick={() => (recording = true)}
                  title={canRecord ? '' : t('Recording needs https or localhost. Uploading works on any address.')}>● {t('Record')}</button>
          <label class="upload">
            {t('⬆ Upload a sound')}
            <input type="file" accept="audio/*,.mp3,.wav,.m4a,.ogg,.flac" onchange={pick}>
          </label>
        </span>
      </div>
      {#if !canRecord}
        <div class="note">{t('Recording needs https or localhost. Uploading works on any address.')}</div>
      {/if}
      {#if !sounds.length}
        <div class="empty small">{t('No sound files yet. Upload a sound.')}</div>
      {:else}
        <ul class="file-list">
          {#each sounds as f (f.name)}
            <li>
              <button type="button" class="play" title={t('Preview')} onclick={() => preview(f.name)}>▶</button>
              {#if renaming === f.name}
                <input type="text" class="rename" bind:value={newName} maxlength="64" aria-label={t('New name of {name}', { name: f.name })}
                       onkeydown={(e) => { if (e.key === 'Enter') rename(f); if (e.key === 'Escape') renaming = null; }}>
                <button type="button" class="act" onclick={() => rename(f)}>{t('Save')}</button>
                <button type="button" class="act" onclick={() => { renaming = null; }}>{t('Cancel')}</button>
              {:else}
                <span class="fname">{f.name}</span>
                <span class="fmeta">{size(f.size)}{f.used_by.length ? ` · ${t('used by {n}', { n: f.used_by.length })}` : ''}</span>
                <button type="button" class="act" onclick={() => { message = ''; editing = { library: f.name }; }}>{t('Edit')}</button>
                <button type="button" class="act" onclick={() => startRename(f)}>{t('Rename')}</button>
                <button type="button" class="act danger" onclick={() => removeFile(f)}>{t('Delete')}</button>
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  {/if}
{/if}

{#if recording}
  <SoundRecorder onrecorded={recorded} oncancel={() => (recording = false)} />
{/if}

<style>
  .folders { display: flex; gap: 0.4rem; margin-bottom: 0.8rem; }
  .tab-chip {
    background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 999px; color: var(--muted);
    padding: 0.2rem 0.8rem; font-family: inherit; font-size: 0.8rem; cursor: pointer;
  }
  .tab-chip.active { border-color: var(--accent); color: var(--text); }
  .empty { color: var(--muted); text-align: center; padding: 1.5rem 0; }
  .empty.small { padding: 0.5rem 0; font-size: 0.85rem; }
  .message { font-size: 0.85rem; color: var(--yellow); margin-bottom: 0.75rem; }
  .box { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 8px; padding: 0.65rem 0.8rem; }
  .box-head { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.5rem; }
  .box-title { font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; }
  ul { list-style: none; padding: 0; margin: 0; }
  .file-list li { display: flex; align-items: center; gap: 0.4rem; padding: 0.3rem 0; border-top: 1px solid var(--glass-border); flex-wrap: wrap; }
  .file-list li:first-child { border-top: none; }
  .fname { font-size: 0.85rem; flex: 1; min-width: 6rem; word-break: break-all; }
  .fmeta { font-size: 0.72rem; color: var(--muted); }
  .play { background: none; border: none; cursor: pointer; color: var(--muted); font-size: 0.8rem; padding: 0 0.25rem; }
  .play:hover { color: var(--accent); }
  .upload, .act {
    background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 6px; color: var(--muted);
    padding: 0.2rem 0.65rem; font-family: inherit; font-size: 0.78rem; cursor: pointer;
  }
  .upload:hover, .act:hover:not(:disabled) { border-color: var(--accent); color: var(--text); }
  .act.danger:hover:not(:disabled) { border-color: var(--red); color: var(--red); }
  .upload input { display: none; }
  .actions { display: inline-flex; align-items: center; gap: 0.4rem; }
  .note { font-size: 0.75rem; color: var(--muted); margin-bottom: 0.4rem; }
  .rename {
    flex: 1; min-width: 8rem; background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 6px;
    color: var(--text); padding: 0.25rem 0.5rem; font-family: inherit; font-size: 0.85rem;
  }
</style>
