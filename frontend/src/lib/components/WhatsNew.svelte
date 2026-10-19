<script>
  import { t } from '../i18n.js';
  // The changes of one version (`changes`: an entry of /api/changelog) in a dialog. It is closed with the button, Escape or a
  // click next to it.
  let { changes, onclose } = $props();

  function onKey(e) {
    if (e.key === 'Escape') { e.preventDefault(); onclose(); }
  }
</script>

<svelte:window onkeydown={onKey} />

<div class="whatsnew-overlay">
  <button type="button" class="whatsnew-backdrop" aria-label={t('Close')} onclick={onclose}></button>
  <div class="whatsnew-box" role="dialog" aria-modal="true" aria-label={t("What's new in v{version}", { version: changes.version })}>
    <h2>{t("What's new in v{version}", { version: changes.version })}</h2>
    <div class="changes">
      {#each changes.sections as s}
        {#if s.name}<div class="section-name">{s.name}</div>{/if}
        <ul>
          {#each s.entries as e}<li>{e}</li>{/each}
        </ul>
      {/each}
    </div>
    <button type="button" class="whatsnew-btn" onclick={onclose}>{t('OK')}</button>
  </div>
</div>

<style>
  .whatsnew-overlay { position: fixed; inset: 0; z-index: 400; display: flex; align-items: center; justify-content: center; padding: 1.5rem 1rem; }
  .whatsnew-backdrop { position: absolute; inset: 0; background: rgba(3, 8, 20, 0.6); backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px); border: none; padding: 0; cursor: default; }
  .whatsnew-box {
    position: relative; display: flex; flex-direction: column; width: 100%; max-width: 620px; max-height: 85vh; padding: 1.5rem 1.5rem 1.25rem;
    border-radius: 20px; background: var(--surface); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); font-family: system-ui, sans-serif;
  }
  h2 { margin: 0 0 1rem; font-size: 1.3rem; color: var(--text); }
  .changes { overflow-y: auto; min-height: 0; margin-bottom: 1.2rem; }
  .section-name { font-size: 0.7rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; margin: 0.8rem 0 0.2rem; }
  .section-name:first-child { margin-top: 0; }
  ul { list-style: none; margin: 0; padding: 0; }
  li { font-size: 0.92rem; line-height: 1.5; color: color-mix(in srgb, var(--text) 85%, transparent); padding: 0.2rem 0 0.2rem 1rem; position: relative; }
  li::before { content: '•'; position: absolute; left: 0.2rem; color: var(--muted); }
  .whatsnew-btn {
    padding: 0.75rem 1rem; border-radius: 999px; font-family: inherit; font-size: 1rem; font-weight: 600; cursor: pointer; border: none;
    background: #166534; color: #fff;
  }
  .whatsnew-btn:hover { background: #15803d; }
</style>
