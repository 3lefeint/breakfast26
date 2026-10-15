<script>
  import { t } from '../../lib/i18n.js';
  // Home's Killer page only handles the setup and the finished screen. The live view is /tv's job;
  // starting a game navigates there, and landing here while a game is already running (back
  // button, another device started it) redirects.
  import { killer } from '../../lib/stores/killer.js';
  import KillerSetup from './KillerSetup.svelte';
  import KillerFinished from './KillerFinished.svelte';
  import PageHeader from '../../lib/components/PageHeader.svelte';

  $effect(() => {
    if ($killer && $killer.active && $killer.state !== 'finished') {
      window.location.href = '/tv';
    }
  });
</script>

<PageHeader title={t('Killer')}>
  {#snippet info()}
    <p>{t('Everyone gets a number and three lives. A double on your own number makes you a killer, from then on you take one life from an opponent with every double on their number. Last one standing wins.')}</p>
    <p><strong>{t('Game settings:')}</strong></p>
    <ul>
      <li><strong>{t('Bull-Off')}:</strong> {t('Everybody throws one dart at the bull, the closest one starts.')}</li>
      <li><strong>{t('Throw for the numbers')}:</strong> {t('Everybody throws one dart with the other hand and gets the number it hits, a double makes a killer at once. Off: the numbers are drawn at random.')}</li>
      <li><strong>{t('Singles')}:</strong> {t('Singles take lives too, not only doubles (triples never do).')}</li>
      <li><strong>{t('Own goal')}:</strong> {t('A killer who hits their own number loses a life.')}</li>
      <li><strong>{t('Random order')}:</strong> {t('The order of play is drawn at random instead of following the list.')}</li>
      <li><strong>{t('Computer opponent')}:</strong> {t('Adds a computer player with a level, its three-dart average, so one person can play a full match.')}</li>
    </ul>
  {/snippet}
</PageHeader>

{#if $killer && $killer.state === 'finished'}
  <KillerFinished />
{:else if !($killer && $killer.active)}
  <KillerSetup />
{/if}
