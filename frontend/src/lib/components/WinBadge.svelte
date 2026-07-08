<script>
  // Plain small win-count number — no pill/circle background (that was
  // the pre-crown design; the crown itself now carries the "most wins"
  // signal, so the number just needs to be legible, not decorative).
  let { wins = 0 } = $props();
</script>

{#if wins}
  <sup class="win-count" title="{wins} elimination win{wins === 1 ? '' : 's'}">{wins}</sup>
{/if}

<style>
  .win-count {
    margin-left: 0.35em;
    font-size: 0.6em; font-weight: 700; color: var(--yellow);
    vertical-align: super;
  }
</style>
