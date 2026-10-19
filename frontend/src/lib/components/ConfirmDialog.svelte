<script>
  import { t } from '../i18n.js';
  // The dialog behind confirmDialog(): mounted once in the Home app, it covers the TV view too.
  import { confirmRequest, answerConfirm } from '../confirm.js';

  function onKey(e) {
    if (!$confirmRequest) return;
    if (e.key === 'Escape') { e.preventDefault(); if (!$confirmRequest.modal) answerConfirm(false); }
    else if (e.key === 'Enter') { e.preventDefault(); answerConfirm(true); }
  }
</script>

<svelte:window onkeydown={onKey} />

{#if $confirmRequest}
  <div class="confirm-overlay">
    <button type="button" class="confirm-backdrop" aria-label={t('OK')} onclick={() => { if (!$confirmRequest.modal) answerConfirm(false); }}></button>
    <div class="confirm-box" role="alertdialog" aria-modal="true" aria-label={$confirmRequest.message}>
      <p class="confirm-text">{$confirmRequest.message}</p>
      <div class="confirm-actions">
        {#if $confirmRequest.info}
          <button type="button" class="confirm-btn yes" onclick={() => answerConfirm(true)}>{t('OK')}</button>
        {:else}
          <button type="button" class="confirm-btn" onclick={() => answerConfirm(false)}>{$confirmRequest.no ?? t('No')}</button>
          <button type="button" class="confirm-btn yes" onclick={() => answerConfirm(true)}>{$confirmRequest.yes ?? t('Yes')}</button>
        {/if}
      </div>
    </div>
  </div>
{/if}

<style>
  .confirm-overlay { position: fixed; inset: 0; z-index: 400; display: flex; align-items: center; justify-content: center; padding: 1.5rem 1rem; }
  .confirm-backdrop { position: absolute; inset: 0; background: rgba(3, 8, 20, 0.6); backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px); border: none; padding: 0; cursor: default; }
  .confirm-box {
    position: relative; width: 100%; max-width: 460px; padding: 1.5rem 1.5rem 1.25rem; border-radius: 20px;
    background: var(--surface); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow);
  }
  .confirm-text { margin: 0 0 1.4rem; font-size: 1.15rem; font-weight: 600; line-height: 1.4; color: var(--text); }
  .confirm-actions { display: flex; gap: 0.8rem; }
  .confirm-btn {
    flex: 1; padding: 0.75rem 1rem; border-radius: 999px; font-family: inherit; font-size: 1rem; font-weight: 600; cursor: pointer;
    background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2);
    transition: border-color 0.15s, color 0.15s, background 0.15s;
  }
  .confirm-btn:hover { border-color: var(--accent); color: var(--accent); }
  .confirm-btn.yes { background: #166534; border-color: transparent; color: #fff; }
  .confirm-btn.yes:hover { background: #15803d; color: #fff; }
</style>
