<script>
  // Fixes a misrecognized dart before it's pulled: click the spot on the
  // dartboard, or use the multiplier + number pad. Opened by tapping D1/D2/D3
  // on the live Elimination view (only while that dart has a value already),
  // and from the X01 view's Board button.
  import { api } from '../../lib/api.js';
  import DartBoard from '../../lib/components/DartBoard.svelte';

  let { dartIndex, onClose, endpoint = '/api/elimination/correct-dart' } = $props();

  let mult = $state(1); // 1=Single, 2=Double, 3=Triple

  function fieldFor(n) {
    return (mult === 1 ? 'S' : mult === 2 ? 'D' : 'T') + n;
  }

  async function submit(field) {
    await api('POST', endpoint, { dart: dartIndex + 1, field });
    onClose();
  }
</script>

<div class="modal-overlay">
  <button type="button" class="overlay-backdrop" aria-label="Close" onclick={onClose}></button>
  <div class="modal-box">
    <div class="section-title">Correct D{dartIndex + 1}</div>

    <DartBoard onSelect={submit} />

    <div class="pad-label">Or pick a field</div>
    <div class="mult-row">
      <button class="btn-mult" class:sel={mult === 1} onclick={() => (mult = 1)}>Single</button>
      <button class="btn-mult" class:sel={mult === 2} onclick={() => (mult = 2)}>Double</button>
      <button class="btn-mult" class:sel={mult === 3} onclick={() => (mult = 3)}>Triple</button>
    </div>

    <div class="number-grid">
      {#each Array.from({ length: 20 }, (_, i) => i + 1) as n}
        <button class="btn-num" onclick={() => submit(fieldFor(n))}>{n}</button>
      {/each}
    </div>

    <div class="special-row">
      <button onclick={() => submit('25')}>Bull (25)</button>
      <button onclick={() => submit('50')}>D-Bull (50)</button>
      <button onclick={() => submit('0')}>Miss</button>
    </div>

    <button class="btn btn-add" style="width:100%" onclick={onClose}>Cancel</button>
  </div>
</div>

<style>
  .section-title { font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 1rem; }
  .modal-overlay { position: fixed; inset: 0; z-index: 100; display: flex; align-items: flex-start; justify-content: center; overflow-y: auto; padding: 1.5rem 1rem; }
  .overlay-backdrop { position: absolute; inset: 0; z-index: 0; background: rgba(3, 8, 20, 0.55); backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px); border: none; padding: 0; cursor: default; }
  .modal-box { position: relative; z-index: 1; background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); border-radius: 16px; padding: 1.25rem; max-width: 480px; width: 100%; }
  .pad-label { font-size: 0.75rem; color: var(--muted); text-align: center; margin: 0.9rem 0 0.6rem; }
  .mult-row { display: flex; gap: 0.5rem; margin-bottom: 1rem; }
  .btn-mult {
    flex: 1; background: var(--glass); border: 1px solid var(--glass-border); color: var(--text);
    border-radius: 10px; padding: 0.6rem; font-size: 0.95rem; font-weight: 600; cursor: pointer;
    transition: border-color 0.15s, color 0.15s, background 0.15s;
  }
  .btn-mult:hover { border-color: var(--accent); }
  .btn-mult.sel { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
  .number-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 0.5rem; margin-bottom: 1rem; }
  .btn-num {
    background: var(--glass); border: 1px solid var(--glass-border); color: var(--text);
    border-radius: 10px; padding: 0.6rem 0; font-size: 1rem; font-weight: 700; cursor: pointer;
    transition: border-color 0.15s, color 0.15s;
  }
  .btn-num:hover { border-color: var(--accent); color: var(--accent); }
  .special-row { display: flex; gap: 0.5rem; margin-bottom: 1.25rem; }
  .special-row button {
    flex: 1; background: var(--glass); border: 1px solid var(--glass-border); color: var(--text);
    border-radius: 10px; padding: 0.6rem 0.4rem; font-size: 0.85rem; font-weight: 600; cursor: pointer;
    transition: border-color 0.15s, color 0.15s;
  }
  .special-row button:hover { border-color: var(--accent); color: var(--accent); }
  .btn { border: none; border-radius: 8px; padding: 0.65rem 1.5rem; font-size: 0.95rem; font-weight: 600; cursor: pointer; transition: opacity 0.15s; }
  .btn:hover { opacity: 0.85; }
  .btn-add { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); padding: 0.5rem 1rem; }
</style>
