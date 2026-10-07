<script>
  import { t } from '../../lib/i18n.js';
  // Stats tab shell: the chips pick the game mode whose stats are shown.
  import PageHeader from '../../lib/components/PageHeader.svelte';
  import StatsX01 from './stats/StatsX01.svelte';
  import StatsElimination from './stats/StatsElimination.svelte';
  import StatsTargetBattle from './stats/StatsTargetBattle.svelte';
  import StatsKiller from './stats/StatsKiller.svelte';
  import StatsFieldTraining from './stats/StatsFieldTraining.svelte';
  import StatsBlackBelt from './stats/StatsBlackBelt.svelte';
  import StatsCheckoutTraining from './stats/StatsCheckoutTraining.svelte';

  const MODES = [
    { id: 'x01', label: 'X01' },
    { id: 'elimination', label: t('Elimination') },
    { id: 'target_battle', label: t('Target Battle') },
    { id: 'killer', label: t('Killer') },
    { id: 'field_training', label: t('Training') },
    { id: 'black_belt', label: t('Black Belt') },
    { id: 'checkout_training', label: t('Checkout') },
  ];

  function remembered() {
    try {
      const saved = localStorage.getItem('statsMode');
      return MODES.some((m) => m.id === saved) ? saved : 'x01';
    } catch (e) {
      return 'x01';
    }
  }

  let mode = $state(remembered());

  function select(id) {
    mode = id;
    try { localStorage.setItem('statsMode', id); } catch (e) { /* remembering is optional */ }
  }
</script>

<PageHeader title={t('Stats')} />

<div class="chips" role="tablist" aria-label={t('Stats view')}>
  {#each MODES as m}
    <button type="button" role="tab" class="chip" class:active={mode === m.id} aria-selected={mode === m.id}
            onclick={() => select(m.id)}>{m.label}</button>
  {/each}
</div>

{#if mode === 'x01'}
  <StatsX01 />
{:else if mode === 'target_battle'}
  <StatsTargetBattle />
{:else if mode === 'killer'}
  <StatsKiller />
{:else if mode === 'field_training'}
  <StatsFieldTraining />
{:else if mode === 'black_belt'}
  <StatsBlackBelt />
{:else if mode === 'checkout_training'}
  <StatsCheckoutTraining />
{:else}
  <StatsElimination />
{/if}

<style>
  .chips { display: flex; gap: 0.4rem; margin-bottom: 1.25rem; flex-wrap: wrap; }
  .chip {
    background: var(--glass); border: 1px solid var(--glass-border); color: var(--muted); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2);
    border-radius: 20px; padding: 0.35rem 1rem; font-family: inherit;
    font-size: 0.85rem; cursor: pointer;
  }
  .chip:hover { border-color: var(--accent); color: var(--text); }
  .chip.active { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); font-weight: 700; }
</style>
