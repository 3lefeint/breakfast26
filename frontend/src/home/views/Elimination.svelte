<script>
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
      window.location.href = '/tv';
    }
  });
</script>

<PageHeader title="Elimination" />

{#if $elimination && $elimination.state === 'finished'}
  <EliminationFinished />
{:else if !($elimination && $elimination.active)}
  {#if !onlineOpen}
    <div class="mode-chips" role="tablist" aria-label="Game type">
      <button type="button" role="tab" class="mode-chip" class:active={mode === 'local'} aria-selected={mode === 'local'} onclick={() => (mode = 'local')}>Local</button>
      <button type="button" role="tab" class="mode-chip" class:active={mode === 'online'} aria-selected={mode === 'online'} onclick={() => (mode = 'online')}>Online</button>
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
  .mode-chip { background: var(--bg); border: 1px solid var(--border); color: var(--muted); border-radius: 20px; padding: 0.35rem 1rem; font-family: inherit; font-size: 0.85rem; cursor: pointer; }
  .mode-chip:hover { border-color: var(--accent); color: var(--text); }
  .mode-chip.active { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); font-weight: 700; }
</style>
