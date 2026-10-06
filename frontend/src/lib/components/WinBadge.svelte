<script>
  import { t } from '../i18n.js';
  // Plain small win-count number — no pill/circle background (that was
  // the pre-crown design; the crown itself now carries the "most wins"
  // signal, so the number just needs to be legible, not decorative).
  let { wins = 0 } = $props();
</script>

{#if wins}
  <sup class="win-count" title={wins === 1 ? t('{n} elimination win', { n: wins }) : t('{n} elimination wins', { n: wins })}>{wins}</sup>
{/if}

<style>
  .win-count {
    margin-left: 0.35em;
    font-size: 0.6em; font-weight: 700; color: var(--yellow);
    vertical-align: super;
  }
</style>
