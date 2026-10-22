<script>
  import { onMount } from 'svelte';
  import { apiJson } from '../../lib/api.js';
  import { t } from '../../lib/i18n.js';
  import Toggle from '../../lib/components/Toggle.svelte';
  // Settings → Connections → Circle of friends: the matches of this installation go to the friends who should get
  // them and theirs come here, as the admin of the circle decided (rules and mappings live at the relay). This section
  // shows the state of the sync and has the local switch; the state is read when the section opens and on Sync now.

  let info = $state(null);
  let busy = $state(false);
  let error = $state('');

  async function load() {
    try {
      info = await apiJson('GET', '/api/circle');
    } catch (e) {
      console.error('circle status failed:', e);
    }
  }

  async function setEnabled(enabled) {
    error = '';
    const res = await apiJson('POST', '/api/circle/enabled', { enabled });
    if (res.error) error = res.error; else info = { available: true, ...res };
  }

  async function syncNow() {
    busy = true; error = '';
    try {
      const res = await apiJson('POST', '/api/circle/sync');
      if (res.error) error = res.error; else info = { available: true, ...res };
    } catch (e) {
      error = String(e);
    } finally {
      busy = false;
    }
  }

  let queued = $state(null);

  // Queues the history: every finished match that the circle does not have yet. They go out in rounds, within the daily limit of the relay.
  async function sendAll() {
    busy = true; error = ''; queued = null;
    try {
      const res = await apiJson('POST', '/api/circle/send-all');
      if (res.error) error = res.error; else { queued = res.queued; info = { available: true, ...res }; }
    } catch (e) {
      error = String(e);
    } finally {
      busy = false;
    }
  }

  const when = (seconds) => (seconds ? new Date(seconds * 1000).toLocaleString('en-GB', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) : t('never'));

  onMount(load);
</script>

{#if info?.available && info.registered}
  <div class="section">
    <div class="title">{t('Circle of friends')}</div>
    <p class="note">{t('Your matches go to the friends the admin of the circle named for the players in them, and their matches come here. Which players and sites belong to it is decided at the relay.')}</p>
    <Toggle label={t('Share matches with the circle')} wide bind:checked={info.enabled} onchange={setEnabled} />
    {#if info.enabled}
      <div class="state">
        <div><span>{t('Approved by the admin')}</span><b>{info.approved === null ? '—' : info.approved ? t('yes') : t('not yet')}</b></div>
        <div><span>{t('Last sent')}</span><b>{when(info.last_push)}</b></div>
        <div><span>{t('Last fetched')}</span><b>{when(info.last_pull)}</b></div>
        <div><span>{t('Waiting to be sent')}</span><b>{info.pending}</b></div>
        <div><span>{t('Sent / received')}</span><b>{info.pushed} / {info.pulled}</b></div>
      </div>
      {#if info.approved === false}<p class="note">{t('Waiting for the admin to approve this site.')}</p>
      {:else if info.error}<p class="note error">{info.error}</p>{/if}
      {#if error}<p class="note error">{error}</p>{/if}
      {#if info.paused_until}<p class="note">{t('The relay is not taking more for now, the sync goes on at {time}.', { time: when(info.paused_until) })}</p>{/if}
      <div class="buttons">
        <button type="button" class="btn" disabled={busy || info.running} onclick={syncNow}>{t('Sync now')}</button>
        <button type="button" class="btn" disabled={busy} onclick={sendAll}>{t('Send all matches')}</button>
      </div>
      {#if queued !== null}<p class="note">{t('{n} matches are queued.', { n: queued })}</p>{/if}
      <p class="note">{t('Send all matches puts every finished match the circle does not have yet into the queue, for the history or after the admin mapped a player. A large history takes some days.')}</p>
    {/if}
  </div>
{/if}

<style>
  .section {
    background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur);
    border-radius: 16px; padding: 1.25rem 1.4rem; margin-bottom: 1.25rem;
  }
  .title { font-size: 0.78rem; color: var(--muted); font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 1rem; }
  .note { font-size: 0.75rem; color: var(--muted); margin: 0 0 0.75rem; }
  .note.error { color: var(--red); }
  .state { display: grid; gap: 0.35rem; margin: 0.25rem 0 0.9rem; font-size: 0.9rem; }
  .state div { display: flex; justify-content: space-between; gap: 1rem; max-width: 26rem; }
  .state span { color: var(--muted); }
  .buttons { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 0.75rem; }
  .btn { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 8px; padding: 0.5rem 1rem; font-size: 0.9rem; font-weight: 600; font-family: inherit; cursor: pointer; transition: opacity 0.15s; }
  .btn:hover { opacity: 0.85; }
  .btn:disabled { opacity: 0.4; cursor: default; }
</style>
