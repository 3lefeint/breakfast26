<script>
  import { openTv } from '../../lib/router.js';
  import { t } from '../../lib/i18n.js';
  // Home's Random checkout page only handles the setup and the finished screen. The live view is
  // the TV view's job; starting a run navigates there, and landing here while a run is already open (back
  // button, another device started it) redirects.
  import { checkoutTraining } from '../../lib/stores/checkoutTraining.js';
  import CheckoutTrainingSetup from './CheckoutTrainingSetup.svelte';
  import CheckoutTrainingFinished from './CheckoutTrainingFinished.svelte';
  import PageHeader from '../../lib/components/PageHeader.svelte';

  $effect(() => {
    if ($checkoutTraining && $checkoutTraining.active && $checkoutTraining.state !== 'finished') {
      openTv();
    }
  });
</script>

<PageHeader title={t('Random checkout')} back="#checkout-trainer">
  {#snippet info()}
    <p>{t('Random checkout is a drill for one player. A score you can finish with three darts is drawn and you throw it on the board. Finish it on a double, the bull\'s eye counts. The Stats page shows which scores work and which do not.')}</p>
    <p><strong>{t('Game settings:')}</strong></p>
    <ul>
      <li><strong>{t('Scores')}:</strong> {t('The range the score is drawn from.')}</li>
      <li><strong>{t('Attempts')}:</strong> {t('Number of scores to throw in a run.')}</li>
      <li><strong>{t('Standard route')}:</strong> {t('The standard route to the finish is shown while you throw.')}</li>
    </ul>
  {/snippet}
</PageHeader>

{#if $checkoutTraining && $checkoutTraining.state === 'finished'}
  <CheckoutTrainingFinished />
{:else if !($checkoutTraining && $checkoutTraining.active)}
  <CheckoutTrainingSetup />
{/if}
