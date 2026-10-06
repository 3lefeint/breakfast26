<script>
  import { t } from '../../lib/i18n.js';
  // Home's Target Battle page only handles the setup and the finished screen. The live view is /tv's
  // job; starting a game navigates there, and landing here while a game is already running (back
  // button, another device started it) redirects.
  import { targetBattle } from '../../lib/stores/targetBattle.js';
  import TargetBattleSetup from './TargetBattleSetup.svelte';
  import TargetBattleFinished from './TargetBattleFinished.svelte';
  import PageHeader from '../../lib/components/PageHeader.svelte';

  $effect(() => {
    if ($targetBattle && $targetBattle.active && $targetBattle.state !== 'finished') {
      window.location.href = '/tv';
    }
  });
</script>

<PageHeader title={t('Target Battle')} />

{#if $targetBattle && $targetBattle.state === 'finished'}
  <TargetBattleFinished />
{:else if !($targetBattle && $targetBattle.active)}
  <TargetBattleSetup />
{/if}
