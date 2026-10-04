<script>
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

<PageHeader title="Killer" />

{#if $killer && $killer.state === 'finished'}
  <KillerFinished />
{:else if !($killer && $killer.active)}
  <KillerSetup />
{/if}
