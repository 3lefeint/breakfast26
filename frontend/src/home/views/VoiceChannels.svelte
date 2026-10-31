<script>
  import { onMount } from 'svelte';
  import { t } from '../../lib/i18n.js';
  // The voice chat channels of the circle that this site sees: a click opens the channel in its own tab (a page on the relay).
  // The admin makes the channels and ticks the sites for them.
  import PageHeader from '../../lib/components/PageHeader.svelte';
  import Panel from '../../lib/components/Panel.svelte';
  import { openVoiceChannel } from '../../lib/voice.js';

  let channels = $state([]);
  let loaded = $state(false);
  let error = $state('');
  let blockedUrl = $state('');
  let busy = $state(false);

  async function load() {
    error = '';
    const res = await fetch('/api/voice/channels').then((r) => r.json()).catch(() => ({ error: 'Breakfast did not answer' }));
    if (res.error) error = res.error;
    else channels = res.channels;
    loaded = true;
  }

  async function open(channel) {
    busy = true; error = ''; blockedUrl = '';
    const res = await openVoiceChannel(channel.id);
    if (res.error) error = res.error;
    else if (res.blocked) blockedUrl = res.url;
    busy = false;
  }

  onMount(load);
</script>

<PageHeader title={t('Voice chat')} back="#home" />

<Panel title={t('Channels')}>
  <p class="note">{t('Talk to the other sites of the circle without a match. Keep the tab open while you talk, and use a headset to avoid echo.')}
    <button type="button" class="btn small" onclick={load}>{t('Refresh')}</button></p>
  {#if error}<p class="note error">{t(error)}</p>{/if}
  {#if blockedUrl}<p class="note"><a href={blockedUrl} target="_blank" rel="noopener">{t('Open the voice chat')}</a></p>{/if}
  {#if loaded && !error}
    {#if !channels.length}
      <p class="empty">{t('No channel for this site yet. The admin of the circle makes channels and chooses which sites see them.')}</p>
    {:else}
      <div class="channels">
        {#each channels as channel (channel.id)}
          <button type="button" class="btn" disabled={busy} onclick={() => open(channel)}>{t('🎧 {name}', { name: channel.name })}</button>
        {/each}
      </div>
    {/if}
  {/if}
</Panel>

<style>
  .note { font-size: 0.85rem; color: var(--muted); margin: 0 0 0.75rem; }
  .note.error { color: var(--red); }
  .empty { color: var(--muted); font-size: 0.9rem; }
  .channels { display: flex; flex-wrap: wrap; gap: 0.6rem; }
  .btn {
    background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 10px; padding: 0.6rem 1.2rem;
    font-size: 0.95rem; font-weight: 600; font-family: inherit; cursor: pointer; transition: border-color 0.15s;
  }
  .btn.small { padding: 0.25rem 0.7rem; font-size: 0.8rem; }
  .btn:hover { border-color: var(--accent); }
  .btn:disabled { opacity: 0.4; cursor: default; }
</style>
