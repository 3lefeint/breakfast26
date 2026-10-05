<script>
  // The result of a finished Black Belt run on the TV.
  import { rematch, stopRun, undoTurn } from '../../lib/blackBelt.js';
  import BlackBeltResult from '../../lib/components/BlackBeltResult.svelte';
  import ConfettiBurst from '../../lib/components/ConfettiBurst.svelte';

  let { bb } = $props();

  async function undoLast() {
    if (!confirm('Undo the last turn and resume the run?')) return;
    await undoTurn();
  }

  async function done() {
    await stopRun();
    window.location.href = '/#black-belt';
  }
</script>

{#if bb.result?.belt}<ConfettiBurst />{/if}

<div class="finished">
  <BlackBeltResult {bb} large />
  <div class="actions">
    <button class="btn" onclick={() => rematch(bb)}>↻ Again</button>
    <button class="btn ghost" onclick={undoLast}>↩ Undo last turn</button>
    <button class="btn ghost" onclick={done}>Done</button>
  </div>
</div>

<style>
  .finished { flex: 1; min-height: 0; display: flex; flex-direction: column; justify-content: center; gap: 1.6rem; padding: 1.5rem 3vw; overflow-y: auto; }
  .actions { display: flex; gap: 0.8rem; flex-wrap: wrap; }
  .btn { background: #166534; color: #fff; border: none; border-radius: 999px; padding: 0.7rem 1.6rem; font-size: 1rem; font-weight: 600; cursor: pointer; }
  .btn.ghost { background: var(--surface); color: var(--muted); border: 1px solid var(--border); }
  .btn.ghost:hover { border-color: var(--accent); color: var(--text); }
</style>
