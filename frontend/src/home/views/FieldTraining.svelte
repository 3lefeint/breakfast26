<script>
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

<PageHeader title="Field Training" />

{#if $fieldTraining && $fieldTraining.state === 'finished'}
  <FieldTrainingFinished />
{:else if !($fieldTraining && $fieldTraining.active)}
  <FieldTrainingSetup />
{/if}
