<script>
  import { openTv } from '../../lib/router.js';
  import { t } from '../../lib/i18n.js';
  // Home's Target Battle page only handles the setup and the finished screen. The live view is the TV view's
  // job; starting a game navigates there, and landing here while a game is already running (back
  // button, another device started it) redirects.
  import { targetBattle } from '../../lib/stores/targetBattle.js';
  import TargetBattleSetup from './TargetBattleSetup.svelte';
  import TargetBattleFinished from './TargetBattleFinished.svelte';
  import PageHeader from '../../lib/components/PageHeader.svelte';

  $effect(() => {
    if ($targetBattle && $targetBattle.active && $targetBattle.state !== 'finished') {
      openTv();
    }
  });
</script>

<PageHeader title={t('Target Battle')}>
  {#snippet info()}
    <p>{t('In Target Battle all players throw at the same target number in every round, and only darts on that number score. The player with the most points after the last round wins.')}</p>
    <p><strong>{t('Game settings:')}</strong></p>
    <ul>
      <li><strong>{t('Rounds')}:</strong> {t('Number of rounds to play.')}</li>
      <li><strong>{t('Targets')}:</strong> {t('Random: a wheel picks the target of every round. Fixed order: you set the target of every round yourself.')}</li>
      <li><strong>{t('Scoring')}:</strong> {t('Standard scores 1 point for a single, 2 for a double and 3 for a triple. The other profiles let only singles, doubles or triples count, to practice one of them.')}</li>
      <li><strong>{t('Tiebreak')}:</strong> {t('The players tied for the lead play on until one has the highest score of a round.')}</li>
      <li><strong>{t('Random order')}:</strong> {t('The order of play is drawn at random instead of following the list.')}</li>
    </ul>
  {/snippet}
</PageHeader>

{#if $targetBattle && $targetBattle.state === 'finished'}
  <TargetBattleFinished />
{:else if !($targetBattle && $targetBattle.active)}
  <TargetBattleSetup />
{/if}
