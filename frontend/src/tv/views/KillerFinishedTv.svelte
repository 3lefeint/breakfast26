<script>
  // The result of a finished Killer game on the TV: the placements with their numbers, the winner
  // marked with the crown, and the darts of the last turn. A dart tapped here is corrected and the
  // game resumes when that turn did not decide it after all.
  import { cap } from '../../lib/util.js';
  import { api } from '../../lib/api.js';
  import { rematch, stopGame, ruleChips, dartLabel } from '../../lib/killer.js';
  import Crown from '../../lib/components/Crown.svelte';
  import ConfettiBurst from '../../lib/components/ConfettiBurst.svelte';
  import DartCorrectModal from './DartCorrectModal.svelte';

  let { killer } = $props();

  let rows = $derived([...(killer.players || [])].sort((a, b) => a.placement - b.placement));
  let lastDarts = $derived(killer.last_turn?.darts || []);
  let correctingIndex = $state(null);

  async function undo() {
    if (!confirm('Undo the last turn and resume the game?')) return;
    await api('POST', '/api/killer/undo');
  }

  async function done() {
    await stopGame();
    window.location.href = '/#killer';
  }
</script>

<ConfettiBurst />

<div class="finished">
  <div class="heading">{cap(killer.winner || '')} wins</div>
  <div class="meta">{ruleChips(killer).join(' · ')}</div>
  <ul class="results">
    {#each rows as p (p.name)}
      <li class:winner={p.name === killer.winner}>
        <span class="place">{p.placement}</span>
        <span class="who">
          <span class="swatch" style="background: {p.color || 'var(--muted)'}; {p.ring ? `outline: 3px ${p.ring.dash ? 'dashed' : 'solid'} ${p.ring.color}; outline-offset: 1px;` : ''}"></span>
          <span class="name-crown">{#if p.name === killer.winner}<Crown />{/if}{cap(p.name)}</span>
          <span class="number">#{p.number}</span>
        </span>
        <span class="lives">{p.lives > 0 ? '❤️'.repeat(p.lives) : '☠️'}</span>
      </li>
    {/each}
  </ul>
  {#if lastDarts.length}
    <div class="last">
      <span class="last-label">Last turn, {cap(killer.last_turn.player)}</span>
      {#each lastDarts as d, i}
        <button type="button" class="dart-chip" onclick={() => (correctingIndex = i)}>{dartLabel(d)}</button>
      {/each}
    </div>
  {/if}
  <div class="actions">
    <button class="btn" onclick={() => rematch(killer)}>↻ Rematch</button>
    <button class="btn ghost" onclick={undo}>↩ Undo last turn</button>
    <button class="btn ghost" onclick={done}>Done</button>
  </div>
</div>

{#if correctingIndex != null}
  <DartCorrectModal dartIndex={correctingIndex} onClose={() => (correctingIndex = null)}
                    endpoint="/api/killer/correct-last-dart" />
{/if}

<style>
  .finished { flex: 1; min-height: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 1.4rem; padding: 1.5rem 2rem; }
  .heading { font-size: clamp(2rem, 5vw, 4.2rem); font-weight: 800; color: var(--green); text-align: center; }
  .meta { color: var(--muted); font-size: clamp(0.8rem, 1.3vw, 1.2rem); margin-top: -1rem; }
  .results { list-style: none; padding: 0; width: min(36rem, 90vw); max-height: 42vh; overflow-y: auto; }
  .results li {
    display: grid; grid-template-columns: 2.5rem 1fr auto; align-items: center; gap: 1rem;
    padding: 0.6rem 1.2rem; margin-top: 0.6rem; border-radius: 12px;
    background: var(--surface); border: 1px solid var(--border); font-size: clamp(1.1rem, 2.2vw, 1.9rem);
  }
  .results li.winner { border-color: color-mix(in srgb, var(--green) 45%, var(--border)); }
  .place { color: var(--muted); font-weight: 700; }
  .who { display: flex; align-items: baseline; gap: 0.7em; }
  .name-crown { position: relative; display: inline-block; }
  .swatch { width: 0.9em; height: 0.9em; border-radius: 50%; flex-shrink: 0; align-self: center; }
  .number { color: var(--muted); font-size: 0.7em; }
  .last { display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap; justify-content: center; }
  .last-label { color: var(--muted); font-size: clamp(0.85rem, 1.4vw, 1.3rem); }
  .dart-chip { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 0.4rem 1rem; font-family: inherit; font-size: clamp(1rem, 1.8vw, 1.6rem); font-weight: 700; color: var(--text); cursor: pointer; }
  .dart-chip:hover { border-color: var(--accent); }
  .actions { display: flex; gap: 0.8rem; flex-wrap: wrap; justify-content: center; }
  .btn { background: #166534; color: #fff; border: none; border-radius: 999px; padding: 0.7rem 1.6rem; font-size: 1rem; font-weight: 600; cursor: pointer; }
  .btn.ghost { background: var(--surface); color: var(--muted); border: 1px solid var(--border); }
  .btn.ghost:hover { border-color: var(--accent); color: var(--text); }
</style>
