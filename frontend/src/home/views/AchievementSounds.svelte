<script>
  import { t } from '../../lib/i18n.js';
  // Settings → Achievements (shown with the Dev tab): which sound each achievement plays when it is
  // earned. Every achievement lists what plays now (an assignment, the `achievement_<id>` file or the
  // general `achievement` file) and can be given one or more files of the achievements folder, which are
  // previewed here. The files themselves are managed in the Sounds tab. A change is saved at once into `[achievements.sounds]`
  // of config.toml and applies without a restart.
  import { onMount } from 'svelte';
  import { shownName } from '../../lib/util.js';
  import { apiJson } from '../../lib/api.js';
  import Toggle from '../../lib/components/Toggle.svelte';

  const URL = '/api/admin/achievement-sounds';
  const MODES = { general: t('General'), x01: 'X01', elimination: t('Elimination'), killer: t('Killer'),
                  target_battle: t('Target Battle'), field_training: t('Field Training'), black_belt: t('Black Belt'), easter_egg: t('Easter eggs') };
  const SOURCE_LABEL = { assigned: t('assigned'), id: t('file name'), generic: t('general sound'), circle: t('from the circle'), none: t('no sound') };

  let data = $state(null);
  let error = $state('');
  let message = $state('');
  let search = $state('');
  let mode = $state('all');
  let playing = null;

  async function load() {
    try {
      const body = await fetch(URL).then((r) => r.json());
      if (body.error) { error = body.error; data = null; } else { error = ''; data = body; }
    } catch (e) {
      error = t('Could not load the achievements.');
    }
  }
  onMount(load);

  let rows = $derived((data?.achievements || []).filter((a) =>
    (mode === 'all' || a.mode === mode)
    && (!search.trim() || `${a.names?.en} ${a.names?.de} ${a.id}`.toLowerCase().includes(search.trim().toLowerCase()))));

  function preview(file) {
    if (playing) playing.pause();
    playing = new Audio(`/api/sound/${encodeURIComponent(file)}`);
    playing.play().catch(() => { message = t('Could not play {file}.', { file }); });
  }

  async function assign(a, files) {
    message = '';
    const res = await fetch(`${URL}/${a.id}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ files }),
    }).then((r) => r.json());
    if (res.error) { message = t(res.error); return; }
    await load();
  }

  async function adopt(a) {
    message = '';
    const res = await apiJson('POST', `${URL}/${a.id}/adopt`);
    if (res.error) { message = t(res.error); return; }
    await load();
  }

  const add = (a, file) => file && assign(a, [...a.assigned, file]);
  const remove = (a, file) => assign(a, a.assigned.filter((f) => f !== file));

  let share = $state(false);
  $effect(() => { if (data) share = !!data.share; });
  async function setShare() {
    const res = await apiJson('POST', '/api/circle/share-achievement-sounds', { enabled: share });
    if (res.error) { message = t(res.error); share = !share; }
  }

  function describe(a) {
    const now = a.plays_now;
    if (now.source === 'none') return t('No sound');
    const from = now.source === 'circle' && a.shared?.origin ? ` (${a.shared.origin})` : '';
    return `${SOURCE_LABEL[now.source]}${from}: ${now.files.join(', ')}`;
  }
</script>

{#if error}
  <div class="empty">{error.startsWith('locked') ? t('Unlock the Dev tab first.') : t(error)}</div>
{:else if !data}
  <div class="empty">{t('Loading…')}</div>
{:else}
  <div class="intro">
    {t('Without an assignment an achievement plays')} <code>achievement_&lt;id&gt;.mp3</code> {t('from the achievements folder, else')} <code>{t('achievement.mp3')}</code>{t('. Give it one or more files here and one of them is picked at random.')}
  </div>

  <div class="note">{t('The files are uploaded, cut and renamed in the Sounds tab.')}</div>
  <div class="share">
    <Toggle label={t('Share these sounds with the circle')} wide bind:checked={share} onchange={setShare} />
    <span class="note">{t('The other installations use a shared sound for an achievement they have no sound of their own for. Only share sounds you are free to share; 2 MB each at most.')}</span>
  </div>

  <div class="toolbar">
    <input type="search" placeholder={t('Search')} bind:value={search} aria-label={t('Search achievements')}>
    <select bind:value={mode} aria-label={t('Game mode')}>
      <option value="all">{t('All modes')}</option>
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
          {#if a.tiers}<span class="chip">{t('tiers {list}', { list: a.tiers.join(' · ') })}</span>{/if}
        </div>
        <div class="now" class:none={a.plays_now.source === 'none'}>{t('Plays now · {what}', { what: describe(a) })}</div>
        <div class="assigned">
          {#each a.assigned as file (file)}
            <span class="file" class:missing={a.missing.includes(file)}>
              <button type="button" class="play" title={t('Preview')} disabled={a.missing.includes(file)}
                      onclick={() => preview(file)}>▶</button>
              {file}{a.missing.includes(file) ? ' ' + t('(missing)') : ''}
              <button type="button" class="remove" title={t('Remove')} onclick={() => remove(a, file)}>×</button>
            </span>
          {/each}
          {#if a.shared}
            {#each a.shared.files as file (file)}
              <span class="file circle" title={t('Shared by {site}', { site: a.shared.origin })}>
                <button type="button" class="play" title={t('Preview')} onclick={() => preview(file)}>▶</button>
                {file} · {a.shared.origin}
              </span>
            {/each}
            <button type="button" class="adopt" title={t('Make this your own assignment; it stays when the other site changes its sound.')}
                    onclick={() => adopt(a)}>{t('Take over')}</button>
          {/if}
          <select aria-label={t('Add a sound to {name}', { name: a.names?.en })} onchange={(e) => { add(a, e.target.value); e.target.value = ''; }}>
            <option value="">{t('+ Add a sound…')}</option>
            {#each data.files.filter((f) => !a.assigned.includes(f)) as f}<option value={f}>{f}</option>{/each}
          </select>
        </div>
      </li>
    {/each}
  </ul>
  {#if !rows.length}<div class="empty">{t('No achievement matches.')}</div>{/if}
{/if}

<style>
  .empty { color: var(--muted); text-align: center; padding: 1.5rem 0; }
  .intro { color: var(--muted); font-size: 0.85rem; margin-bottom: 1rem; line-height: 1.45; }
  code { background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 4px; padding: 0 0.3rem; }
  .toolbar { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.75rem; }
  input[type="search"], select {
    background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 6px; color: var(--text);
    padding: 0.4rem 0.6rem; font-family: inherit; font-size: 0.85rem;
  }
  input[type="search"] { flex: 1; min-width: 10rem; }
  .empty.small { padding: 0.5rem 0; font-size: 0.85rem; }
  .message { font-size: 0.85rem; color: var(--yellow); margin-bottom: 0.75rem; }
  .list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.5rem; }
  .list li { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 8px; padding: 0.65rem 0.8rem; }
  .head { display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; }
  .name { font-weight: 700; margin-right: 0.3rem; }
  .chip { font-size: 0.7rem; color: var(--muted); border: 1px solid var(--glass-border); border-radius: 999px; padding: 0 0.5rem; }
  .now { font-size: 0.78rem; color: var(--muted); margin: 0.3rem 0 0.4rem; }
  .now.none { color: var(--yellow); }
  .assigned { display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; }
  .file {
    display: inline-flex; align-items: center; gap: 0.35rem; font-size: 0.8rem;
    background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 999px; padding: 0.1rem 0.3rem 0.1rem 0.2rem;
  }
  .file.circle { border-style: dashed; color: var(--muted); }
  .adopt { background: none; border: 1px solid var(--glass-border); border-radius: 999px; color: var(--muted); cursor: pointer; font-family: inherit; font-size: 0.78rem; padding: 0.1rem 0.6rem; }
  .adopt:hover { border-color: var(--accent); color: var(--accent); }
  .file.missing { border-color: var(--red); color: var(--red); }
  .play, .remove { background: none; border: none; cursor: pointer; color: var(--muted); font-size: 0.8rem; padding: 0 0.25rem; }
  .play:hover { color: var(--accent); }
  .play:disabled { cursor: default; opacity: 0.4; }
  .remove:hover { color: var(--red); }
  .share { display: flex; flex-direction: column; gap: 0.3rem; margin-bottom: 0.8rem; }
  .share .note { margin-bottom: 0; }
  .note { font-size: 0.8rem; color: var(--muted); margin-bottom: 0.8rem; }
</style>
