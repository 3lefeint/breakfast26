<script>
  import { onMount } from 'svelte';
  import { t } from '../../lib/i18n.js';
  // The name call of a player: one or more sounds of the sound library that are played instead of the voice-pack file of the
  // name. A sound is picked from the library or recorded here (recorder, then the sound editor, saved into the library).
  // The assignment is stored with the player in the database.
  import { players } from '../../lib/stores/players.js';
  import { apiJson } from '../../lib/api.js';
  import { shownName } from '../../lib/util.js';
  import Panel from '../../lib/components/Panel.svelte';
  import SoundRecorder from './SoundRecorder.svelte';
  import SoundEditor from './SoundEditor.svelte';

  let data = $state(null);              // { sounds: { name: [file] }, files: [file] }
  let player = $state('');
  let message = $state('');
  let recording = $state(false);        // the recorder dialog is open
  let editing = $state(null);           // { file, suggest } while the recording is in the sound editor
  let playing = null;

  // The browser allows the microphone only on https or on localhost, so on a plain http address the button stays off.
  const canRecord = typeof window !== 'undefined' && window.isSecureContext && !!navigator.mediaDevices?.getUserMedia
    && typeof MediaRecorder !== 'undefined';

  async function load() {
    const body = await apiJson('GET', '/api/players/sounds');
    data = body.error ? null : body;
  }
  onMount(load);

  let assigned = $derived(player && data ? data.sounds[player] || [] : []);
  let addable = $derived((data?.files || []).filter((f) => !assigned.includes(f)));

  async function assign(files) {
    message = '';
    const res = await apiJson('PUT', `/api/players/${encodeURIComponent(player)}/sounds`, { files });
    if (res.error) { message = t(res.error); return; }
    await load();
  }
  const add = (file) => file && assign([...assigned, file]);
  const remove = (file) => assign(assigned.filter((f) => f !== file));

  function preview(file) {
    if (playing) playing.pause();
    playing = new Audio(`/api/sound/${encodeURIComponent(file)}?t=${Date.now()}`);
    playing.play().catch(() => { message = t('Could not play {file}.', { file }); });
  }

  // The first free `<name>-<n>.mp3` for the recording.
  function suggestion() {
    const stem = player.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^A-Za-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'name';
    const taken = data?.files || [];
    let n = 1;
    while (taken.includes(`${stem}-${n}.mp3`)) n += 1;
    return `${stem}-${n}.mp3`;
  }

  function recorded(file) {
    recording = false;
    message = '';
    editing = { file, suggest: suggestion() };
  }

  async function saved(file) {
    editing = null;
    await load();
    await assign([...assigned, file]);
  }
</script>

<Panel title={t('Name sounds')}>
  <div class="note">{t('A name sound is added to the name of the voice pack. One of them is played at random.')}</div>
  {#if data}
    <div class="row">
      <select bind:value={player} aria-label={t('Player')}>
        <option value="">{t('Player')}</option>
        {#each $players.known as name (name)}<option value={name}>{shownName(name)}</option>{/each}
      </select>
      <button type="button" class="btn" disabled={!player || !canRecord} onclick={() => (recording = true)}
              title={canRecord ? '' : t('Recording needs https or localhost. Uploading works on any address.')}>● {t('Record')}</button>
    </div>
    <div class="assigned">
      {#if player}
        {#each assigned as file (file)}
          {@const gone = !data.files.includes(file)}
          <span class="file" class:missing={gone}>
            <button type="button" class="play" title={t('Preview')} disabled={gone} onclick={() => preview(file)}>▶</button>
            {file}{gone ? ' ' + t('(missing)') : ''}
            <button type="button" class="remove" title={t('Remove')} onclick={() => remove(file)}>×</button>
          </span>
        {/each}
        <select aria-label={t('Add a sound to {name}', { name: shownName(player) })}
                onchange={(e) => { add(e.target.value); e.target.value = ''; }}>
          <option value="">{t('+ Add a sound…')}</option>
          {#each addable as f (f)}<option value={f}>{f}</option>{/each}
        </select>
      {/if}
    </div>
    <div class="message">{message}</div>
  {/if}
</Panel>

{#if recording}
  <SoundRecorder onrecorded={recorded} oncancel={() => (recording = false)} />
{/if}

{#if editing}
  <div class="back" role="presentation">
    <div class="dialog" role="dialog" aria-modal="true" aria-label={t('Record a sound')}>
      <SoundEditor file={editing.file} suggest={editing.suggest} taken={data?.files || []}
                   onsaved={saved} oncancel={() => { editing = null; }} />
    </div>
  </div>
{/if}

<style>
  .note { font-size: 0.8rem; color: var(--muted); margin-bottom: 0.8rem; }
  .row { display: flex; align-items: center; gap: 0.75rem; }
  .row select { flex: 1; min-width: 0; }
  select {
    background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); color: var(--text);
    border-radius: 12px; padding: 0.65rem 1rem; font-size: 1rem; font-family: inherit;
  }
  .assigned select { border-radius: 6px; padding: 0.3rem 0.6rem; font-size: 0.85rem; }
  select:focus { outline: none; border-color: var(--accent); }
  .btn {
    background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 12px;
    padding: 0.65rem 1.3rem; font-size: 1rem; font-family: inherit; cursor: pointer;
  }
  .btn:hover:not(:disabled) { border-color: var(--accent); }
  .btn:disabled { opacity: 0.4; cursor: default; }
  .assigned { display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; min-height: 2.4rem; margin-top: 0.75rem; }
  .file {
    display: inline-flex; align-items: center; gap: 0.35rem; font-size: 0.8rem;
    background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 999px; padding: 0.1rem 0.3rem 0.1rem 0.2rem;
  }
  .file.missing { border-color: var(--red); color: var(--red); }
  .play, .remove { background: none; border: none; cursor: pointer; color: var(--muted); font-size: 0.8rem; padding: 0 0.25rem; }
  .play:hover { color: var(--accent); }
  .play:disabled { cursor: default; opacity: 0.4; }
  .remove:hover { color: var(--red); }
  .message { min-height: 1.2rem; margin-top: 0.4rem; font-size: 0.85rem; color: var(--yellow); }
  .back { position: fixed; inset: 0; z-index: 1000; display: flex; align-items: center; justify-content: center; background: rgba(0, 0, 0, 0.55); }
  .dialog {
    width: min(52rem, calc(100vw - 2rem)); max-height: calc(100vh - 2rem); overflow: auto; padding: 1rem 1.2rem;
    border-radius: 12px; background: var(--bg, #0f1115); border: 1px solid var(--glass-border); box-shadow: 0 12px 40px rgba(0, 0, 0, 0.5);
  }
</style>
