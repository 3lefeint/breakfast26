<script>
  // The result of a finished Field Training run on Home: another run with the same setup, a new
  // setup, or undoing the turn that ended the run.
  import { fieldTraining } from '../../lib/stores/fieldTraining.js';
  import { rematch, stopRun, undoTurn } from '../../lib/fieldTraining.js';
  import FieldTrainingResult from '../../lib/components/FieldTrainingResult.svelte';

  let ft = $derived($fieldTraining);

  async function again() {
    if (await rematch(ft)) window.location.href = '/tv';
  }

  async function undoLast() {
    if (!confirm('Undo the last turn and resume the run?')) return;
    await undoTurn();
  }
</script>

{#if ft && ft.result}
  <div class="section">
    <FieldTrainingResult {ft} />
    <div class="actions">
      <button class="btn btn-start" onclick={again}>↻ Again</button>
      <button class="btn ghost" onclick={stopRun}>New run</button>
      <button class="btn ghost" onclick={undoLast}>↩ Undo last turn</button>
    </div>
  </div>
{/if}

<style>
  .section { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; margin-bottom: 1rem; }
  .actions { display: flex; gap: 0.6rem; flex-wrap: wrap; margin-top: 1.5rem; }
  .btn { border: none; border-radius: 8px; padding: 0.65rem 1.4rem; font-size: 0.95rem; font-weight: 600; cursor: pointer; }
  .btn-start { background: #166534; color: #fff; }
  .btn.ghost { background: var(--bg); color: var(--muted); border: 1px solid var(--border); }
  .btn.ghost:hover { border-color: var(--accent); color: var(--text); }
</style>
