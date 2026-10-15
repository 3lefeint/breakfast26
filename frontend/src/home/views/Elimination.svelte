<script>
  import { openTv } from '../../lib/router.js';
  import { t } from '../../lib/i18n.js';
  // Home's Elimination tab only handles Setup and the Finished/rematch
  // screen — the live view is /tv's job (and does it better: full-width
  // layout, tap-to-correct darts, the voice-call role toggle). Starting
  // a game (from Setup or a rematch) already navigates to /tv directly;
  // this redirect only catches the edge case of landing on #elimination
  // while a game is *already* active (e.g. back button, another device
  // already started one).
  import { elimination } from '../../lib/stores/elimination.js';
  import { online } from '../../lib/stores/online.js';
  import EliminationSetup from './EliminationSetup.svelte';
  import OnlineLobby from './OnlineLobby.svelte';
  import EliminationFinished from './EliminationFinished.svelte';
  import PageHeader from '../../lib/components/PageHeader.svelte';

  // Local game or online match; an open online match always shows itself.
  let mode = $state('local');
  let onlineOpen = $derived(!!$online && !($elimination && $elimination.active));

  $effect(() => {
    if ($elimination && $elimination.active && $elimination.state !== 'finished') {
      openTv();
    }
  });
</script>

<PageHeader title={t('Elimination')}>
  {#snippet info()}
    <p>{t('Elimination is a game for any number of players. Every player starts with a number of lives. In every turn you have to score more than the turn before; if you do not, you lose a life. The last player with lives left wins.')}</p>
    <p><strong>{t('Game settings:')}</strong></p>
    <ul>
      <li><strong>{t('Lives per player')}:</strong> {t('Number of lives every player starts with.')}</li>
      <li><strong>{t('Random order')}:</strong> {t('The order of play is drawn at random instead of following the list.')}</li>
      <li><strong>{t('Computer opponent')}:</strong> {t('Adds a computer player with a level, its three-dart average, so one person can play a full match.')}</li>
    </ul>
  {/snippet}
</PageHeader>

{#if $elimination && $elimination.state === 'finished'}
  <EliminationFinished />
{:else if !($elimination && $elimination.active)}
  {#if !onlineOpen}
    <div class="mode-chips" role="tablist" aria-label={t('Game type')}>
      <button type="button" role="tab" class="mode-chip" class:active={mode === 'local'} aria-selected={mode === 'local'} onclick={() => (mode = 'local')}>{t('Local')}</button>
      <button type="button" role="tab" class="mode-chip" class:active={mode === 'online'} aria-selected={mode === 'online'} onclick={() => (mode = 'online')}>{t('Online')}</button>
    </div>
  {/if}
  {#if onlineOpen || mode === 'online'}
    <OnlineLobby />
  {:else}
    <EliminationSetup />
  {/if}
{/if}

<style>
  .mode-chips { display: flex; gap: 0.4rem; margin-bottom: 1rem; }
  .mode-chip { background: var(--glass); border: 1px solid var(--glass-border); color: var(--muted); border-radius: 20px; padding: 0.35rem 1rem; font-family: inherit; font-size: 0.85rem; cursor: pointer; }
  .mode-chip:hover { border-color: var(--accent); color: var(--text); }
  .mode-chip.active { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); font-weight: 700; }
</style>
