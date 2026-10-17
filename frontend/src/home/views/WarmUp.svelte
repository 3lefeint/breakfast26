<script>
  import { openTv } from '../../lib/router.js';
  import { t } from '../../lib/i18n.js';
  // Home's Warm-up page only handles the setup and the finished screen. The live view is the TV view's
  // job; starting a run navigates there, and landing here while a run is open redirects.
  import { warmUp } from '../../lib/stores/warmUp.js';
  import WarmUpSetup from './WarmUpSetup.svelte';
  import WarmUpFinished from './WarmUpFinished.svelte';
  import PageHeader from '../../lib/components/PageHeader.svelte';

  $effect(() => {
    if ($warmUp && $warmUp.active && $warmUp.state !== 'finished') {
      openTv();
    }
  });
</script>

<PageHeader title={t('Warm-up')}>
  {#snippet info()}
    <p>{t('The warm-up is a round over every segment of the board for one player. Throw at each field until it is hit, there is no limit of darts per field. After a hit the next field is up, also for the darts left in the same turn.')}</p>
    <p><strong>{t('The stations:')}</strong></p>
    <ul>
      <li>{t('The big singles from 1 to 20, between the triple ring and the double ring.')}</li>
      <li>{t('The bull.')}</li>
      <li>{t('The small singles from 1 to 20, between the bull and the triple ring.')}</li>
      <li>{t('The bull again.')}</li>
      <li>{t('The doubles from 1 to 20.')}</li>
      <li>{t('The bull once more.')}</li>
      <li>{t('The triples from 1 to 20.')}</li>
      <li>{t('The bull\'s eye.')}</li>
    </ul>
    <p><strong>{t('Game settings:')}</strong></p>
    <ul>
      <li><strong>{t('Stations')}:</strong> {t('All of them, or only the ones you switch on, for example the big singles and the triples. The run keeps the order above, the bull comes between the stations you switch on and the bull\'s eye last.')}</li>
    </ul>
    <p>{t('The run ends when every field has been hit. The result shows how many darts it took and how that compares with your earlier runs over the same stations.')}</p>
  {/snippet}
</PageHeader>

{#if $warmUp && $warmUp.state === 'finished'}
  <WarmUpFinished />
{:else if !($warmUp && $warmUp.active)}
  <WarmUpSetup />
{/if}
