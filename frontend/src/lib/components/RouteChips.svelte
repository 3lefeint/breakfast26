<script>
  // A finishing route as a row of chips, one per dart: T20 T20 Bull.
  import { fieldName } from '../checkoutTraining.js';

  let { route = [], hit = null } = $props();
</script>

<span class="route">
  {#each route as field, i}
    <span class="chip" class:hit={hit === i}>{fieldName(field)}</span>
  {/each}
</span>

<style>
  .route { display: inline-flex; gap: 0.35em; flex-wrap: wrap; align-items: center; }
  .chip { min-width: 2.2em; text-align: center; padding: 0.1em 0.55em; border: 1px solid var(--glass-border); border-radius: 8px; background: var(--glass); font-weight: 800; }
  .chip.hit { border-color: var(--green); color: var(--green); }
</style>
