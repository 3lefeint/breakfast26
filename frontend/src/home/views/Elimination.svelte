<script>
  // Home's Elimination tab only handles Setup and the Finished/rematch
  // screen — the live view is /tv's job (and does it better: full-width
  // layout, tap-to-correct darts, the voice-call role toggle). Starting
  // a game (from Setup or a rematch) already navigates to /tv directly;
  // this redirect only catches the edge case of landing on #elimination
  // while a game is *already* active (e.g. back button, another device
  // already started one).
  import { elimination } from '../../lib/stores/elimination.js';
  import EliminationSetup from './EliminationSetup.svelte';
  import EliminationFinished from './EliminationFinished.svelte';
  import PageHeader from '../../lib/components/PageHeader.svelte';

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
  <EliminationSetup />
{/if}
