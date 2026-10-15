<script>
  import { openTv } from '../../lib/router.js';
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
      openTv();
    }
  });
</script>

<PageHeader title={t('X01')}>
  {#snippet info()}
    <p>{t('X01 is a darts game in which all players start with a set score and aim to reduce it to exactly zero by hitting the dartboard. Depending on the game settings, specific rules apply to starting and finishing a leg. The first player to reach exactly zero while meeting the checkout requirements wins the leg. A match can consist of multiple legs.')}</p>
    <p><strong>{t('Game settings:')}</strong></p>
    <ul>
      <li><strong>{t('Base Score')}:</strong> {t('Starting score, e.g. 301 or 501.')}</li>
      <li><strong>{t('In Mode')}:</strong> {t('Determines how the leg must be started:')}
        <ul>
          <li><strong>{t('Straight In')}:</strong> {t('The game can start with any valid scoring hit.')}</li>
          <li><strong>{t('Double In')}:</strong> {t('The game starts only when a double is hit.')}</li>
          <li><strong>{t('Master In')}:</strong> {t('The game starts only when a double, triple, or bullseye is hit.')}</li>
        </ul>
      </li>
      <li><strong>{t('Out Mode')}:</strong> {t('Determines how the leg must be finished:')}
        <ul>
          <li><strong>{t('Straight Out')}:</strong> {t('The score must reach exactly zero. Any valid scoring hit can finish the leg.')}</li>
          <li><strong>{t('Double Out')}:</strong> {t('The leg must be finished with a hit on a double or the double bull.')}</li>
          <li><strong>{t('Master Out')}:</strong> {t('The leg must be finished with a double, triple, or double bull.')}</li>
        </ul>
      </li>
      <li><strong>{t('Max Rounds')}:</strong> {t('Maximum number of rounds per leg.')}</li>
      <li><strong>{t('Legs to win')}:</strong> {t('Number of legs required to win the match.')}</li>
      <li><strong>{t('Bull-Off')}:</strong> {t('Determines whether players throw at the bullseye before the game to decide who starts.')}</li>
    </ul>
  {/snippet}
</PageHeader>

{#if $x01Own && $x01Own.state === 'finished'}
  <X01Finished />
{:else if !($x01Own && $x01Own.active)}
  <X01Setup />
{/if}
