<script>
  // Settings → Achievements (shown with the Dev tab): which sound each achievement plays when it is
  // earned. Every achievement lists what plays now (an assignment, the `achievement_<id>` file or the
  // general `achievement` file) and can be given one or more files of the achievements folder, which are
  // previewed here. The Files section uploads, renames and deletes the files themselves. A change is saved at once into `[achievements.sounds]`
  // of config.toml and applies without a restart.
  import { onMount } from 'svelte';
  import { cap } from '../../lib/util.js';

  const URL = '/api/admin/achievement-sounds';
  const MODES = { general: 'General', x01: 'X01', elimination: 'Elimination', killer: 'Killer',
                  target_battle: 'Target Battle', field_training: 'Field Training', black_belt: 'Black Belt', easter_egg: 'Easter eggs' };
  const SOURCE_LABEL = { assigned: 'assigned', id: 'file name', generic: 'general sound', none: 'no sound' };

  let data = $state(null);
  let error = $state('');
  let message = $state('');
  let search = $state('');
  let mode = $state('all');
  let uploading = $state(false);
  let renaming = $state(null);
  let newName = $state('');
  let playing = null;

  async function load() {
    try {
      const body = await fetch(URL).then((r) => r.json());
      if (body.error) { error = body.error; data = null; } else { error = ''; data = body; }
    } catch (e) {
      error = 'Could not load the achievements.';
    }
  }
  onMount(load);

  let rows = $derived((data?.achievements || []).filter((a) =>
    (mode === 'all' || a.mode === mode)
    && (!search.trim() || `${a.names?.en} ${a.names?.de} ${a.id}`.toLowerCase().includes(search.trim().toLowerCase()))));

  function preview(file) {
    if (playing) playing.pause();
    playing = new Audio(`/api/sound/${encodeURIComponent(file)}`);
    playing.play().catch(() => { message = `Could not play ${file}.`; });
  }

  async function assign(a, files) {
    message = '';
    const res = await fetch(`${URL}/${a.id}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ files }),
    }).then((r) => r.json());
    if (res.error) { message = res.error; return; }
    await load();
  }

  const add = (a, file) => file && assign(a, [...a.assigned, file]);
  const remove = (a, file) => assign(a, a.assigned.filter((f) => f !== file));

  async function upload(event) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    uploading = true;
    message = '';
    try {
      const res = await fetch(`${URL}/upload?name=${encodeURIComponent(file.name)}`, { method: 'POST', body: file })
        .then((r) => r.json());
      message = res.error ? res.error : `Uploaded ${res.file}.`;
      if (!res.error) await load();
    } catch (e) {
      message = 'The upload failed.';
    } finally {
      uploading = false;
    }
  }

  function startRename(file) {
    renaming = file;
    newName = file;
  }

  async function rename(file) {
    message = '';
    const res = await fetch(`${URL}/files/${encodeURIComponent(file)}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: newName.trim() }),
    }).then((r) => r.json());
    if (res.error) { message = res.error; return; }
    renaming = null;
    await load();
  }

  async function removeFile(f) {
    const users = f.used_by.map((u) => u.names?.en || u.id).join(', ');
    const warning = users ? `\n\nIt is assigned to: ${users}. It is taken out there.` : '';
    if (!confirm(`Delete ${f.name}?${warning}`)) return;
    message = '';
    const res = await fetch(`${URL}/files/${encodeURIComponent(f.name)}`, { method: 'DELETE' }).then((r) => r.json());
    if (res.error) { message = res.error; return; }
    await load();
  }

  function size(bytes) {
    return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(bytes < 10240 ? 1 : 0)} KB`;
  }

  function describe(a) {
    const now = a.plays_now;
    if (now.source === 'none') return 'No sound';
    return `${SOURCE_LABEL[now.source]}: ${now.files.join(', ')}`;
  }
</script>

{#if error}
  <div class="empty">{error.startsWith('locked') ? 'Unlock the Dev tab first.' : error}</div>
{:else if !data}
  <div class="empty">Loading…</div>
{:else}
  <div class="intro">
    Without an assignment an achievement plays <code>achievement_&lt;id&gt;.mp3</code> from the achievements
    folder, else <code>achievement.mp3</code>. Give it one or more files here and one of them is picked at random.
  </div>

  <div class="files">
    <div class="files-head">
      <span class="files-title">Files in the achievements folder</span>
      <label class="upload" class:busy={uploading}>
        {uploading ? 'Uploading…' : '⬆ Upload an mp3'}
        <input type="file" accept=".mp3,audio/mpeg" onchange={upload} disabled={uploading}>
      </label>
    </div>
    {#if !data.file_details.length}
      <div class="empty small">No sound files yet. Upload an mp3.</div>
    {:else}
      <ul class="file-list">
        {#each data.file_details as f (f.name)}
          <li>
            <button type="button" class="play" title="Preview" onclick={() => preview(f.name)}>▶</button>
            {#if renaming === f.name}
              <input class="rename" type="text" bind:value={newName} aria-label="New name of {f.name}"
                     onkeydown={(e) => { if (e.key === 'Enter') rename(f.name); if (e.key === 'Escape') renaming = null; }}>
              <button type="button" class="act" onclick={() => rename(f.name)}>Save</button>
              <button type="button" class="act" onclick={() => (renaming = null)}>Cancel</button>
            {:else}
              <span class="fname">{f.name}</span>
              <span class="fmeta">{size(f.size)}{f.used_by.length ? ` · used by ${f.used_by.length}` : ''}</span>
              <button type="button" class="act" onclick={() => startRename(f.name)}>Rename</button>
              <button type="button" class="act danger" onclick={() => removeFile(f)}>Delete</button>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  </div>

  <div class="toolbar">
    <input type="search" placeholder="Search" bind:value={search} aria-label="Search achievements">
    <select bind:value={mode} aria-label="Game mode">
      <option value="all">All modes</option>
      {#each Object.entries(MODES) as [key, label]}<option value={key}>{label}</option>{/each}
    </select>
  </div>
  {#if message}<div class="message">{message}</div>{/if}

  <ul class="list">
    {#each rows as a (a.id)}
      <li>
        <div class="head">
          <span class="name">{a.names?.en || a.id}</span>
          <span class="chip">{MODES[a.mode] || a.mode}</span>
          <span class="chip">{a.difficulty === 'hidden' ? 'secret' : a.difficulty.replace('_', ' ')}</span>
          {#if a.tiers}<span class="chip">tiers {a.tiers.join(' · ')}</span>{/if}
        </div>
        <div class="now" class:none={a.plays_now.source === 'none'}>Plays now · {describe(a)}</div>
        <div class="assigned">
          {#each a.assigned as file (file)}
            <span class="file" class:missing={a.missing.includes(file)}>
              <button type="button" class="play" title="Preview" disabled={a.missing.includes(file)}
                      onclick={() => preview(file)}>▶</button>
              {file}{a.missing.includes(file) ? ' (missing)' : ''}
              <button type="button" class="remove" title="Remove" onclick={() => remove(a, file)}>×</button>
            </span>
          {/each}
          <select aria-label="Add a sound to {a.names?.en}" onchange={(e) => { add(a, e.target.value); e.target.value = ''; }}>
            <option value="">+ Add a sound…</option>
            {#each data.files.filter((f) => !a.assigned.includes(f)) as f}<option value={f}>{f}</option>{/each}
          </select>
        </div>
      </li>
    {/each}
  </ul>
  {#if !rows.length}<div class="empty">No achievement matches.</div>{/if}
{/if}

<style>
  .empty { color: var(--muted); text-align: center; padding: 1.5rem 0; }
  .intro { color: var(--muted); font-size: 0.85rem; margin-bottom: 1rem; line-height: 1.45; }
  code { background: var(--bg); border: 1px solid var(--border); border-radius: 4px; padding: 0 0.3rem; }
  .toolbar { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.75rem; }
  input[type="search"], select {
    background: var(--bg); border: 1px solid var(--border); border-radius: 6px; color: var(--text);
    padding: 0.4rem 0.6rem; font-family: inherit; font-size: 0.85rem;
  }
  input[type="search"] { flex: 1; min-width: 10rem; }
  .upload {
    background: var(--bg); border: 1px solid var(--border); border-radius: 6px; padding: 0.4rem 0.8rem;
    font-size: 0.85rem; cursor: pointer; color: var(--text);
  }
  .upload:hover { border-color: var(--accent); }
  .upload.busy { opacity: 0.6; cursor: default; }
  .upload input { display: none; }
  .files { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 0.65rem 0.8rem; margin-bottom: 1rem; }
  .files-head { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.5rem; }
  .files-title { font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; }
  .file-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; }
  .file-list li { display: flex; align-items: center; gap: 0.5rem; padding: 0.3rem 0; border-top: 1px solid var(--border); flex-wrap: wrap; }
  .file-list li:first-child { border-top: none; }
  .fname { font-size: 0.85rem; flex: 1; min-width: 8rem; word-break: break-all; }
  .fmeta { font-size: 0.75rem; color: var(--muted); }
  .rename { flex: 1; min-width: 8rem; background: var(--bg); border: 1px solid var(--border); border-radius: 6px; color: var(--text); padding: 0.25rem 0.5rem; font-family: inherit; font-size: 0.85rem; }
  .act { background: var(--bg); border: 1px solid var(--border); border-radius: 6px; color: var(--muted); padding: 0.15rem 0.6rem; font-family: inherit; font-size: 0.75rem; cursor: pointer; }
  .act:hover { border-color: var(--accent); color: var(--text); }
  .act.danger:hover { border-color: var(--red); color: var(--red); }
  .empty.small { padding: 0.5rem 0; font-size: 0.85rem; }
  .message { font-size: 0.85rem; color: var(--yellow); margin-bottom: 0.75rem; }
  .list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.5rem; }
  .list li { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 0.65rem 0.8rem; }
  .head { display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; }
  .name { font-weight: 700; margin-right: 0.3rem; }
  .chip { font-size: 0.7rem; color: var(--muted); border: 1px solid var(--border); border-radius: 999px; padding: 0 0.5rem; }
  .now { font-size: 0.78rem; color: var(--muted); margin: 0.3rem 0 0.4rem; }
  .now.none { color: var(--yellow); }
  .assigned { display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; }
  .file {
    display: inline-flex; align-items: center; gap: 0.35rem; font-size: 0.8rem;
    background: var(--bg); border: 1px solid var(--border); border-radius: 999px; padding: 0.1rem 0.3rem 0.1rem 0.2rem;
  }
  .file.missing { border-color: var(--red); color: var(--red); }
  .play, .remove { background: none; border: none; cursor: pointer; color: var(--muted); font-size: 0.8rem; padding: 0 0.25rem; }
  .play:hover { color: var(--accent); }
  .play:disabled { cursor: default; opacity: 0.4; }
  .remove:hover { color: var(--red); }
</style>
