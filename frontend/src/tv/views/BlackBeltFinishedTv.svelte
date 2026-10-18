<script>
  import { confirmDialog } from '../../lib/confirm.js';
  import { navigate } from '../../lib/router.js';
  import { t } from '../../lib/i18n.js';
  // The result of a finished Black Belt run on the TV.
  import { rematch, stopRun, undoTurn } from '../../lib/blackBelt.js';
  import BlackBeltResult from '../../lib/components/BlackBeltResult.svelte';
  import ConfettiBurst from '../../lib/components/ConfettiBurst.svelte';

  let { bb } = $props();

  async function undoLast() {
    if (!await confirmDialog(t('Undo the last turn and resume the run?'))) return;
    await undoTurn();
  }

  async function done() {
    await stopRun();
    navigate('black-belt');
  }
</script>

{#if bb.result?.belt}<ConfettiBurst />{/if}

<div class="finished">
  <BlackBeltResult {bb} large />
  <div class="actions">
    <button class="btn" onclick={() => rematch(bb)}>{t('↻ Replay')}</button>
    <button class="btn ghost" onclick={undoLast}>{t('↩ Undo')}</button>
    <button class="btn ghost" onclick={done}>{t('✓ Done')}</button>
  </div>
</div>

<style>
  .finished { flex: 1; min-height: 0; display: flex; flex-direction: column; justify-content: center; gap: 1.6rem; padding: 1.5rem 3vw; overflow-y: auto; }
  .actions { display: flex; gap: 1vw; flex-wrap: wrap; }
  .btn { background: #166534; color: #fff; border: none; border-radius: 999px; padding: 0.75rem 2rem; font-size: clamp(1rem, 1.5vw, 1.6rem); font-weight: 600; cursor: pointer; transition: border-color 0.15s, color 0.15s, background 0.15s; }
  .btn:hover { background: #15803d; }
  .btn.ghost { background: var(--glass); color: color-mix(in srgb, var(--text) 82%, transparent); border: 1px solid var(--glass-border); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2); }
  .btn.ghost:hover { background: var(--glass); border-color: var(--accent); color: var(--text); }
</style>
