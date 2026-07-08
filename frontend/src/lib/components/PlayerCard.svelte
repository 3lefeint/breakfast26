<script>
  // Row shape mirrors Players.svelte's header (.player-row-grid, kept in
  // sync with this file's grid-template-columns) — Name | Elimination
  // Wins | X01 Wins | Audio | Hide, so the two win-count types read as
  // labeled columns instead of unlabeled icons.
  let { name, wins = 0, x01Wins = 0, missingAudio = false, onHide = null } = $props();
</script>

<li class="player-card">
  <span class="pname">{name}</span>
  <span class="pwins">{#if wins}🏆 {wins}{/if}</span>
  <span class="pwins">{#if x01Wins}🎯 {x01Wins}{/if}</span>
  <span class="paudio">
    {#if missingAudio}
      <span class="no-audio-icon" title="No recording for this name">🔇</span>
    {/if}
  </span>
  <span class="phide">
    {#if onHide}
      <button class="btn-hide" onclick={() => onHide(name)}>Hide</button>
    {/if}
  </span>
</li>

<style>
  .player-card {
    display: grid;
    grid-template-columns: 1fr 8rem 6rem 3rem 4rem;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 0;
    border-bottom: 1px solid var(--border, #333);
  }
  .pwins { color: var(--muted, #888); font-size: 0.8rem; }
  .paudio, .phide { display: flex; justify-content: flex-end; }
  .no-audio-icon { opacity: 0.5; }
  .btn-hide {
    background: transparent; border: 1px solid var(--border); color: var(--muted);
    font-size: 0.7rem; padding: 0.15rem 0.4rem; border-radius: 4px; cursor: pointer;
  }
  .btn-hide:hover { border-color: var(--accent); color: var(--accent); }
</style>
