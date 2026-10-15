<script>
  // An on/off switch with its label, as the settings of the setup pages use it. `wide` is for a label that is
  // a sentence: it takes the width it needs instead of the fixed label column.
  let { checked = $bindable(false), label, wide = false } = $props();
</script>

<label class="option-row">
  <span class="label" class:wide>{label}</span>
  <span class="switch">
    <input type="checkbox" bind:checked>
    <span class="slider"></span>
  </span>
</label>

<style>
  .option-row { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.8rem; cursor: pointer; }
  .label { font-size: 0.9rem; color: var(--muted); min-width: 8rem; }
  .label.wide { min-width: 0; flex: 0 1 30rem; }
  @media (max-width: 640px) { .label { min-width: 0; flex: 1; } }
  .switch { position: relative; display: inline-block; flex: none; width: 2.8rem; height: 1.5rem; }
  .switch input { opacity: 0; width: 0; height: 0; }
  .slider { position: absolute; inset: 0; border-radius: 999px; background: var(--glass); border: 1px solid var(--glass-border); transition: background 0.15s, border-color 0.15s; }
  .slider::before { content: ''; position: absolute; width: 1.05rem; height: 1.05rem; left: 0.2rem; top: 50%; transform: translateY(-50%); border-radius: 50%; background: var(--muted); transition: transform 0.15s, background 0.15s; }
  .switch input:checked + .slider { background: var(--accent-soft); border-color: var(--accent); }
  .switch input:checked + .slider::before { transform: translate(1.3rem, -50%); background: var(--accent); }
  .switch input:focus-visible + .slider { outline: 2px solid var(--accent); outline-offset: 2px; }
</style>
