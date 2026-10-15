<script>
  import { t } from '../../lib/i18n.js';
  // Home's Field Training page only handles the setup and the finished screen. The live view is
  // /tv's job; starting a run navigates there, and landing here while a run is already open (back
  // button, another device started it) redirects.
  import { fieldTraining } from '../../lib/stores/fieldTraining.js';
  import FieldTrainingSetup from './FieldTrainingSetup.svelte';
  import FieldTrainingFinished from './FieldTrainingFinished.svelte';
  import PageHeader from '../../lib/components/PageHeader.svelte';

  $effect(() => {
    if ($fieldTraining && $fieldTraining.active && $fieldTraining.state !== 'finished') {
      window.location.href = '/tv';
    }
  });
</script>

<PageHeader title={t('Field Training')}>
  {#snippet info()}
    <p>{t('Field Training is a drill for one player: you throw a fixed number of darts at a single field, a number or the bull. The result shows the points, the hit rate and a rating.')}</p>
    <p><strong>{t('Game settings:')}</strong></p>
    <ul>
      <li><strong>{t('Field')}:</strong> {t('The number from 1 to 20, or the bull, you throw at.')}</li>
      <li><strong>{t('Darts')}:</strong> {t('Number of darts of the run. From the standard number on (100 at a number, 50 at the bull) a complete run counts for the rating and the personal best, fewer darts are saved as practice.')}</li>
      <li><strong>{t('Points')}:</strong> {t('On a number: single 1 point, double 2, triple 3. On the bull: outer bull 1 point, bull\'s eye 2 points. Everything else scores 0.')}</li>
    </ul>
  {/snippet}
</PageHeader>

{#if $fieldTraining && $fieldTraining.state === 'finished'}
  <FieldTrainingFinished />
{:else if !($fieldTraining && $fieldTraining.active)}
  <FieldTrainingSetup />
{/if}
