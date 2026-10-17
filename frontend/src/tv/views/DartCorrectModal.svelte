<script>
  import { t } from '../../lib/i18n.js';
  // Fixes a misrecognized dart or enters one the board did not see: press the spot on the dartboard
  // (a magnifier shows it, the dart is stored where it is let go; a press next to the board is a
  // miss). Opened by tapping D1/D2/D3 on the live game views and from the finished views.
  import { api } from '../../lib/api.js';
  import DartBoard from '../../lib/components/DartBoard.svelte';

  let { dartIndex, onClose, endpoint = '/api/elimination/correct-dart' } = $props();

  async function submit(field, point = null) {
    await api('POST', endpoint, { dart: dartIndex + 1, field, ...(point || {}) });
    onClose();
  }
</script>

<div class="modal-overlay">
  <button type="button" class="overlay-backdrop" aria-label={t('Close')} onclick={onClose}></button>
  <div class="modal-box">
    <div class="section-title">{t('Correct D{n}', { n: dartIndex + 1 })}</div>

    <DartBoard onSelect={submit} loupe />

    <button class="btn btn-add" style="width:100%" onclick={onClose}>{t('Cancel')}</button>
  </div>
</div>

<style>
  .section-title { font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 1rem; }
  .modal-overlay { position: fixed; inset: 0; z-index: 100; display: flex; align-items: flex-start; justify-content: center; overflow-y: auto; padding: 1.5rem 1rem; }
  .overlay-backdrop { position: absolute; inset: 0; z-index: 0; background: rgba(3, 8, 20, 0.55); backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px); border: none; padding: 0; cursor: default; }
  .modal-box { position: relative; z-index: 1; background: var(--glass-bar); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); border-radius: 16px; padding: 1.25rem; max-width: min(92vw, 78vh, 720px); width: 100%; --board-max: min(100%, 72vh); }
  .btn { border: none; border-radius: 8px; padding: 0.65rem 1.5rem; font-size: 0.95rem; font-weight: 600; cursor: pointer; transition: opacity 0.15s; margin-top: 1rem; }
  .btn:hover { opacity: 0.85; }
  .btn-add { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); padding: 0.5rem 1rem; }
</style>
