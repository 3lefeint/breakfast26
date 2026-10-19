<script>
  import { t } from '../i18n.js';
  // The one-time notice that a newer release is available, in the corner of the Home app. `onview` opens
  // Settings, `onclose` dismisses it (the version is remembered by the caller).
  let { version, onview, onclose } = $props();
</script>

<div class="update-toast" role="status">
  <span class="text">{t('v{version} available', { version })}</span>
  <button type="button" class="view" onclick={onview}>{t('View')}</button>
  <button type="button" class="close" aria-label={t('Close')} onclick={onclose}>×</button>
</div>

<style>
  .update-toast {
    position: fixed; right: 1.5rem; bottom: 1.5rem; z-index: 300; display: flex; align-items: center; gap: 0.8rem;
    padding: 0.7rem 0.8rem 0.7rem 1.1rem; border-radius: 14px; background: var(--surface);
    border: 1px solid var(--accent); box-shadow: var(--glass-shadow); font-family: system-ui, sans-serif;
  }
  .text { font-weight: 600; color: var(--text); }
  .view {
    padding: 0.4rem 0.9rem; border-radius: 999px; border: 1px solid var(--glass-border); background: var(--glass);
    color: var(--text); font: inherit; font-size: 0.9rem; font-weight: 600; cursor: pointer;
  }
  .view:hover { border-color: var(--accent); color: var(--accent); }
  .close { border: none; background: none; color: var(--muted); font-size: 1.4rem; line-height: 1; cursor: pointer; padding: 0 0.3rem; }
  .close:hover { color: var(--text); }
  @media (max-width: 800px) { .update-toast { right: 1rem; left: 1rem; bottom: calc(5rem + env(safe-area-inset-bottom)); } }
</style>
