<script>
  import { t } from '../../lib/i18n.js';
  // The result of a finished Black Belt run on Home: another run with the same setup, a new setup,
  // or undoing the last turn.
  import { blackBelt } from '../../lib/stores/blackBelt.js';
  import { rematch, stopRun, undoTurn } from '../../lib/blackBelt.js';
  import BlackBeltResult from '../../lib/components/BlackBeltResult.svelte';

  let bb = $derived($blackBelt);

  async function again() {
    if (await rematch(bb)) window.location.href = '/tv';
  }

  async function undoLast() {
    if (!confirm(t('Undo the last turn and resume the run?'))) return;
    await undoTurn();
  }
</script>

{#if bb && bb.result}
  <div class="section">
    <BlackBeltResult {bb} />
    <div class="actions">
      <button class="btn btn-start" onclick={again}>{t('↻ Again')}</button>
      <button class="btn ghost" onclick={stopRun}>{t('New run')}</button>
      <button class="btn ghost" onclick={undoLast}>{t('↩ Undo last turn')}</button>
    </div>
  </div>
{/if}

<style>
  .section { background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); border-radius: 16px; padding: 1.5rem; margin-bottom: 1rem; }
  .actions { display: flex; gap: 0.6rem; flex-wrap: wrap; margin-top: 1.5rem; }
  .btn { border: none; border-radius: 8px; padding: 0.65rem 1.4rem; font-size: 0.95rem; font-weight: 600; cursor: pointer; }
  .btn-start { background: #166534; color: #fff; }
  .btn.ghost { background: var(--glass); color: color-mix(in srgb, var(--text) 82%, transparent); border: 1px solid var(--glass-border); }
  .btn.ghost:hover { border-color: var(--accent); color: var(--text); }
</style>
