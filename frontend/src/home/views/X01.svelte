<script>
  import { t } from '../../lib/i18n.js';
  // Home's X01 page only handles the setup and the finished screen. The live view is /tv's job;
  // starting a match navigates there, and landing here while a match is already running (back
  // button, another device started it) redirects.
  import { x01Own } from '../../lib/stores/x01Own.js';
  import X01Setup from './X01Setup.svelte';
  import X01Finished from './X01Finished.svelte';
  import PageHeader from '../../lib/components/PageHeader.svelte';

  $effect(() => {
    if ($x01Own && $x01Own.active && $x01Own.state !== 'finished') {
      window.location.href = '/tv';
    }
  });
</script>

<PageHeader title={t('X01')} />

{#if $x01Own && $x01Own.state === 'finished'}
  <X01Finished />
{:else if !($x01Own && $x01Own.active)}
  <X01Setup />
{/if}
