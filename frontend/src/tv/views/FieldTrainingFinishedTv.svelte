<script>
  import { t } from '../../lib/i18n.js';
  // The result of a finished Field Training run on the TV.
  import { rematch, stopRun, undoTurn } from '../../lib/fieldTraining.js';
  import FieldTrainingResult from '../../lib/components/FieldTrainingResult.svelte';

  let { ft } = $props();

  async function undoLast() {
    if (!confirm(t('Undo the last turn and resume the run?'))) return;
    await undoTurn();
  }

  async function done() {
    await stopRun();
    window.location.href = '/#field-training';
  }
</script>

<div class="finished">
  <FieldTrainingResult {ft} large />
  <div class="actions">
    <button class="btn" onclick={() => rematch(ft)}>{t('↻ Again')}</button>
    <button class="btn ghost" onclick={undoLast}>{t('↩ Undo last turn')}</button>
    <button class="btn ghost" onclick={done}>{t('Done')}</button>
  </div>
</div>

<style>
  .finished { flex: 1; min-height: 0; display: flex; flex-direction: column; justify-content: center; gap: 1.6rem; padding: 1.5rem 3vw; overflow-y: auto; }
  .actions { display: flex; gap: 0.8rem; flex-wrap: wrap; }
  .btn { background: #166534; color: #fff; border: none; border-radius: 999px; padding: 0.7rem 1.6rem; font-size: 1rem; font-weight: 600; cursor: pointer; }
  .btn.ghost { background: var(--glass); color: color-mix(in srgb, var(--text) 82%, transparent); border: 1px solid var(--glass-border); }
  .btn.ghost:hover { border-color: var(--accent); color: var(--text); }
</style>
