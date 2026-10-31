<script>
  import { t } from '../../../lib/i18n.js';
  // The small window of a voice chat channel: its name can be changed and saved, or the channel deleted.
  let { channel, onsave, ondelete, onclose } = $props();

  let name = $state(channel.name);
  let changed = $derived(name.trim() !== '' && name.trim() !== channel.name);

  function onKey(e) {
    if (e.key === 'Escape') { e.preventDefault(); onclose(); }
    else if (e.key === 'Enter' && changed) { e.preventDefault(); onsave(name.trim()); }
  }
  const focusInput = (node) => { node.focus(); node.select(); };
</script>

<svelte:window onkeydown={onKey} />

<div class="overlay">
  <button type="button" class="backdrop" aria-label={t('Cancel')} onclick={onclose}></button>
  <div class="box" role="dialog" aria-modal="true" aria-label={channel.name}>
    <input type="text" maxlength="40" aria-label={t('Name of a channel')} use:focusInput bind:value={name}>
    <div class="actions">
      <button type="button" class="btn" onclick={ondelete}>{t('Delete')}</button>
      <button type="button" class="btn" onclick={onclose}>{t('Cancel')}</button>
      <button type="button" class="btn primary" disabled={!changed} onclick={() => onsave(name.trim())}>{t('Save')}</button>
    </div>
  </div>
</div>

<style>
  .overlay { position: fixed; inset: 0; z-index: 350; display: flex; align-items: center; justify-content: center; padding: 1.5rem 1rem; }
  .backdrop { position: absolute; inset: 0; background: rgba(3, 8, 20, 0.6); backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px); border: none; padding: 0; cursor: default; }
  .box { position: relative; width: 100%; max-width: 380px; padding: 1.25rem; border-radius: 20px; background: var(--surface); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); }
  .box input { width: 100%; box-sizing: border-box; margin-bottom: 1rem; padding: 0.6rem 0.9rem; border-radius: 12px; font-family: inherit; font-size: 1rem; background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); }
  .box input:focus { outline: none; border-color: var(--accent); }
  .actions { display: flex; gap: 0.6rem; justify-content: flex-end; }
  .btn { padding: 0.5rem 1rem; border-radius: 999px; font-family: inherit; font-size: 0.9rem; font-weight: 600; cursor: pointer; background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); }
  .btn:hover { border-color: var(--accent); }
  .btn.primary { background: var(--accent); border-color: var(--accent); color: #0c0c0f; }
  .btn:disabled { opacity: 0.4; cursor: default; }
</style>
