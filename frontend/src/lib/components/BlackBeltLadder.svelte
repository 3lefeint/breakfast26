<script>
  // The ladder of a Black Belt run: one pill per field in order, the fields done in this attempt
  // filled, the field that is up marked.
  import { stepLabel } from '../blackBelt.js';

  let { steps = [], position = 0, belt = false } = $props();
</script>

<div class="ladder" role="list" aria-label="Ladder">
  {#each steps as field, i}
    <span class="pill" role="listitem" class:done={belt || i < position} class:now={!belt && i === position}>{stepLabel(field)}</span>
  {/each}
</div>

<style>
  .ladder { display: flex; flex-wrap: wrap; gap: 0.3rem; }
  .pill {
    min-width: 2.4em; text-align: center; padding: 0.15em 0.5em; border-radius: 999px;
    border: 1px solid var(--border); color: var(--muted); font-size: 0.8em; font-weight: 700;
  }
  .pill.done { background: var(--accent); border-color: var(--accent); color: #0c0c0f; }
  .pill.now { border-color: var(--accent); color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 30%, transparent); }
</style>
