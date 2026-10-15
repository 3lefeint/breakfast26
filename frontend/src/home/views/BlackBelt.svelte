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

<PageHeader title={t('Black Belt')}>
  {#snippet info()}
    <p>{t('Black Belt is a doubles drill for one player. Hit the double of every field in order, the bull\'s eye comes last. You earn the belt by getting through the whole ladder in one go.')}</p>
    <p><strong>{t('Game settings:')}</strong></p>
    <ul>
      <li><strong>{t('Ladder')}:</strong> {t('From D1 up to D20, or from D20 down to D1.')}</li>
      <li><strong>{t('Darts')}:</strong> {t('Each field has three darts of its own, the darts left in your hand after a hit are bonus darts at the next field. Miss a field with them and the ladder starts again.')}</li>
    </ul>
  {/snippet}
</PageHeader>

{#if $blackBelt && $blackBelt.state === 'finished'}
  <BlackBeltFinished />
{:else if !($blackBelt && $blackBelt.active)}
  <BlackBeltSetup />
{/if}
