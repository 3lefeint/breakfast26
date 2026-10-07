<script>
  import { t } from '../../lib/i18n.js';
  // Home's Random checkout page only handles the setup and the finished screen. The live view is
  // /tv's job; starting a run navigates there, and landing here while a run is already open (back
  // button, another device started it) redirects.
  import { checkoutTraining } from '../../lib/stores/checkoutTraining.js';
  import CheckoutTrainingSetup from './CheckoutTrainingSetup.svelte';
  import CheckoutTrainingFinished from './CheckoutTrainingFinished.svelte';
  import PageHeader from '../../lib/components/PageHeader.svelte';

  $effect(() => {
    if ($checkoutTraining && $checkoutTraining.active && $checkoutTraining.state !== 'finished') {
      window.location.href = '/tv';
    }
  });
</script>

<PageHeader title={t('Random checkout')} back="#checkout-trainer" />

{#if $checkoutTraining && $checkoutTraining.state === 'finished'}
  <CheckoutTrainingFinished />
{:else if !($checkoutTraining && $checkoutTraining.active)}
  <CheckoutTrainingSetup />
{/if}
