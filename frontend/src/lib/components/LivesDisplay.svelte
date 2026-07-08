<script>
  // A heart plays a small pop transition whenever it flips
  // between full/empty (a life gained or lost) — {#key} forces Svelte to
  // re-mount that one heart so the transition actually fires, since the
  // emoji text alone changing wouldn't otherwise re-trigger it.
  import { scale } from 'svelte/transition';

  let { lives = 0, livesMax = 3 } = $props();
</script>

<div class="lives-display">
  {#each Array(livesMax) as _, i}
    {#key i < lives}
      <span class="life-heart" in:scale={{ duration: 250, start: 0.4 }}>{i < lives ? '❤️' : '🤍'}</span>
    {/key}
  {/each}
</div>

<style>
  .lives-display { display: flex; gap: 2px; }
  .life-heart { font-size: inherit; line-height: 1; display: inline-block; }
</style>
