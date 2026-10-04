<script>
  // The result of a finished Killer game on Home: placements, a rematch with the same players and
  // options (new numbers), a new setup, correcting a dart of the last turn or undoing it. A game won
  // by mistake resumes after a correction or an undo.
  import { killer } from '../../lib/stores/killer.js';
  import { api } from '../../lib/api.js';
  import { cap } from '../../lib/util.js';
  import { rematch, stopGame, ruleChips, dartLabel } from '../../lib/killer.js';
  import ConfettiBurst from '../../lib/components/ConfettiBurst.svelte';
  import DartCorrectModal from '../../tv/views/DartCorrectModal.svelte';

  let k = $derived($killer);
  let rows = $derived([...(k?.players || [])].sort((a, b) => a.placement - b.placement));
  let lastDarts = $derived(k?.last_turn?.darts || []);
  let correctingIndex = $state(null);

  async function again() {
    if (await rematch(k)) window.location.href = '/tv';
  }

  async function undoWin() {
    if (!confirm('Undo the last turn and resume the game?')) return;
    await api('POST', '/api/killer/undo');
  }
</script>

{#if k}
  <ConfettiBurst />
  <div class="section finished">
    <div class="heading">{cap(k.winner || '')} wins</div>
    <div class="meta">{ruleChips(k).join(' · ')}</div>
    <ul class="results">
      {#each rows as p (p.name)}
        <li class:winner={p.name === k.winner}>
          <span class="place">{p.placement}</span>
          <span class="who">
            <span class="swatch" style="background: {p.color || 'var(--muted)'}; {p.ring ? `outline: 3px ${p.ring.dash ? 'dashed' : 'solid'} ${p.ring.color}; outline-offset: 1px;` : ''}"></span>
            {cap(p.name)} <span class="number">#{p.number}</span>
          </span>
          <span class="lives">{p.lives > 0 ? '❤️'.repeat(p.lives) : '☠️'}</span>
        </li>
      {/each}
    </ul>
    {#if lastDarts.length}
      <div class="last">
        <span class="last-label">Last turn, {cap(k.last_turn.player)}</span>
        {#each lastDarts as d, i}
          <button type="button" class="dart-chip" onclick={() => (correctingIndex = i)}>{dartLabel(d)}</button>
        {/each}
        <span class="hint">tap a dart to correct it</span>
      </div>
    {/if}
    <div class="actions">
      <button class="btn btn-start" onclick={again}>↻ Rematch</button>
      <button class="btn ghost" onclick={stopGame}>New game</button>
      <button class="btn ghost" onclick={undoWin}>↩ Undo last turn</button>
    </div>
  </div>
{/if}

{#if correctingIndex != null}
  <DartCorrectModal dartIndex={correctingIndex} onClose={() => (correctingIndex = null)}
                    endpoint="/api/killer/correct-last-dart" />
{/if}

<style>
  .section { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; margin-bottom: 1rem; }
  .heading { font-size: 1.6rem; font-weight: 800; color: var(--green); }
  .meta { color: var(--muted); font-size: 0.85rem; margin: 0.25rem 0 1rem; }
  .results { list-style: none; padding: 0; margin-bottom: 1.25rem; }
  .results li { display: grid; grid-template-columns: 2rem 1fr auto; gap: 0.75rem; align-items: center; padding: 0.55rem 0.8rem; margin-top: 0.5rem; border: 1px solid var(--border); border-radius: 10px; background: var(--bg); }
  .results li.winner { border-color: color-mix(in srgb, var(--green) 45%, var(--border)); }
  .place { color: var(--muted); font-weight: 700; }
  .swatch { width: 0.85rem; height: 0.85rem; border-radius: 50%; flex-shrink: 0; }
  .who { display: flex; align-items: center; gap: 0.6rem; }
  .number { color: var(--muted); font-size: 0.85rem; margin-left: 0.2rem; }
  .last { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 1.25rem; }
  .last-label { color: var(--muted); font-size: 0.85rem; }
  .hint { color: var(--muted); font-size: 0.75rem; }
  .dart-chip { background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: 0.3rem 0.8rem; font-family: inherit; font-weight: 700; color: var(--text); cursor: pointer; }
  .dart-chip:hover { border-color: var(--accent); }
  .actions { display: flex; gap: 0.6rem; flex-wrap: wrap; }
  .btn { border: none; border-radius: 8px; padding: 0.65rem 1.4rem; font-size: 0.95rem; font-weight: 600; cursor: pointer; }
  .btn-start { background: #166534; color: #fff; }
  .btn.ghost { background: var(--bg); color: var(--muted); border: 1px solid var(--border); }
  .btn.ghost:hover { border-color: var(--accent); color: var(--text); }
</style>
