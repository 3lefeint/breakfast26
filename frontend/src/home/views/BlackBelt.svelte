<script>
  import { t } from '../../lib/i18n.js';
  // Home's Black Belt page only handles the setup and the finished screen. The live view is /tv's
  // job; starting a run navigates there, and landing here while a run is open redirects.
  import { blackBelt } from '../../lib/stores/blackBelt.js';
  import BlackBeltSetup from './BlackBeltSetup.svelte';
  import BlackBeltFinished from './BlackBeltFinished.svelte';
  import PageHeader from '../../lib/components/PageHeader.svelte';

  $effect(() => {
    if ($blackBelt && $blackBelt.active && $blackBelt.state !== 'finished') {
      window.location.href = '/tv';
    }
  });
</script>

<PageHeader title={t('Black Belt')} />

{#if $blackBelt && $blackBelt.state === 'finished'}
  <BlackBeltFinished />
{:else if !($blackBelt && $blackBelt.active)}
  <BlackBeltSetup />
{/if}
