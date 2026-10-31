<script>
  import { t } from '../i18n.js';
  // The voice chat of an online match: the button (drawn by the page, as a snippet that gets the function that opens the
  // window) and the small window that asks which one: the chat of this match, or one of the channels of the circle that this
  // site sees (the admin makes the channels). Either one opens in its own tab, on the relay's secure page.
  import { openVoiceChat, openVoiceChannel } from '../voice.js';

  let { trigger } = $props();

  let open = $state(false);
  let channels = $state([]);
  let error = $state('');
  let blockedUrl = $state('');

  async function show() {
    open = true;
    error = blockedUrl = '';
    channels = [];
    const res = await fetch('/api/voice/channels').then((r) => r.json()).catch(() => ({}));
    channels = res.channels || [];         // without channels (not linked, not approved) there is the chat of the match
  }

  async function use(opener) {
    error = blockedUrl = '';
    const res = await opener();
    if (res.error) error = t(res.error);
    else if (res.blocked) blockedUrl = res.url;
    else open = false;
  }

  const onKey = (e) => { if (open && e.key === 'Escape') { e.preventDefault(); open = false; } };
</script>

<svelte:window onkeydown={onKey} />

{@render trigger(show)}

{#if open}
  <div class="overlay">
    <button type="button" class="backdrop" aria-label={t('Cancel')} onclick={() => (open = false)}></button>
    <div class="box" role="dialog" aria-modal="true" aria-label={t('Voice chat')}>
      <button type="button" class="choice" onclick={() => use(openVoiceChat)}>{t('Voice chat of this match')}</button>
      {#if channels.length}
        <div class="title">{t('Channels')}</div>
        {#each channels as channel (channel.id)}
          <button type="button" class="choice" onclick={() => use(() => openVoiceChannel(channel.id))}>{channel.name}</button>
        {/each}
      {/if}
      {#if error}<p class="error">{error}</p>{/if}
      {#if blockedUrl}<p class="note"><a href={blockedUrl} target="_blank" rel="noopener">{t('Open the voice chat')}</a></p>{/if}
      <div class="actions"><button type="button" class="cancel" onclick={() => (open = false)}>{t('Cancel')}</button></div>
    </div>
  </div>
{/if}

<style>
  .overlay { position: fixed; inset: 0; z-index: 350; display: flex; align-items: center; justify-content: center; padding: 1.5rem 1rem; font-size: 1rem; }
  .backdrop { position: absolute; inset: 0; background: rgba(3, 8, 20, 0.6); backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px); border: none; padding: 0; cursor: default; }
  .box { position: relative; width: 100%; max-width: 380px; padding: 1.25rem; border-radius: 20px; background: var(--surface); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); display: flex; flex-direction: column; gap: 0.5rem; color: var(--text); }
  .title { margin-top: 0.5rem; font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; }
  .choice { padding: 0.65rem 1rem; border-radius: 12px; font-family: inherit; font-size: 0.95rem; font-weight: 600; text-align: left; cursor: pointer; background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); }
  .choice:hover { border-color: var(--accent); }
  .error { color: var(--red); font-size: 0.85rem; margin: 0; }
  .note { margin: 0; font-size: 0.85rem; }
  .note a { color: var(--accent); }
  .actions { display: flex; justify-content: flex-end; margin-top: 0.5rem; }
  .cancel { padding: 0.45rem 1rem; border-radius: 999px; font-family: inherit; font-size: 0.9rem; font-weight: 600; cursor: pointer; background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); }
</style>
