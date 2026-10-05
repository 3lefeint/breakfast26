<script>
  // Stats tab shell: the chips pick the game mode whose stats are shown.
  import PageHeader from '../../lib/components/PageHeader.svelte';
  import StatsX01 from './stats/StatsX01.svelte';
  import StatsElimination from './stats/StatsElimination.svelte';
  import StatsTargetBattle from './stats/StatsTargetBattle.svelte';
  import StatsKiller from './stats/StatsKiller.svelte';
  import StatsFieldTraining from './stats/StatsFieldTraining.svelte';
  import StatsBlackBelt from './stats/StatsBlackBelt.svelte';

  const MODES = [
    { id: 'x01', label: 'X01' },
    { id: 'elimination', label: 'Elimination' },
    { id: 'target_battle', label: 'Target Battle' },
    { id: 'killer', label: 'Killer' },
    { id: 'field_training', label: 'Training' },
    { id: 'black_belt', label: 'Black Belt' },
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

<PageHeader title="Stats" />

<div class="chips" role="tablist" aria-label="Stats view">
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
{:else}
  <StatsElimination />
{/if}

<style>
  .chips { display: flex; gap: 0.4rem; margin-bottom: 1.25rem; flex-wrap: wrap; }
  .chip {
    background: var(--bg); border: 1px solid var(--border); color: var(--muted);
    border-radius: 20px; padding: 0.35rem 1rem; font-family: inherit;
    font-size: 0.85rem; cursor: pointer;
  }
  .chip:hover { border-color: var(--accent); color: var(--text); }
  .chip.active { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); font-weight: 700; }
</style>
