<script>
  import { t } from '../i18n.js';
  let { show = false } = $props();
</script>

{#if show}
  <span class="freipass-badge">{t('Freipass')}</span>
{/if}

<style>
  .freipass-badge {
    font-size: 0.75rem; background: #78350f; color: var(--yellow);
    border-radius: 4px; padding: 0.15rem 0.4rem; margin-left: 0.5rem;
  }
</style>
