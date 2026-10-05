<script>
  import Avatar from '../../lib/components/Avatar.svelte';
  // The result of a finished Target Battle on Home: placements and scores, a rematch with the same
  // players and options, a new setup, or undoing the turn that ended the game.
  import { targetBattle } from '../../lib/stores/targetBattle.js';
  import { api } from '../../lib/api.js';
  import { cap } from '../../lib/util.js';
  import { rematch, stopGame, SCORING_LABELS } from '../../lib/targetBattle.js';
  import ConfettiBurst from '../../lib/components/ConfettiBurst.svelte';

  let tb = $derived($targetBattle);
  let rows = $derived([...(tb?.players || [])].sort((a, b) => a.placement - b.placement || b.score - a.score));
  let solo = $derived((tb?.players || []).length === 1);

  async function again() {
    if (await rematch(tb)) window.location.href = '/tv';
  }

  async function undoWin() {
    if (!confirm('Undo the last turn and resume the game?')) return;
    await api('POST', '/api/target-battle/undo');
  }
</script>

{#if tb}
  {#if !solo}<ConfettiBurst />{/if}
  <div class="section finished">
    <div class="heading">
      {#if solo}Finished
      {:else if tb.winners.length > 1}{tb.winners.map(cap).join(' and ')} win
      {:else}{cap(tb.winners[0] || '')} wins{/if}
    </div>
    <div class="meta">{tb.rounds} {tb.rounds === 1 ? 'round' : 'rounds'} · {SCORING_LABELS[tb.scoring] || tb.scoring}</div>
    <ul class="results">
      {#each rows as p (p.name)}
        <li class:winner={tb.winners.includes(p.name)}>
          <span class="place">{p.placement}</span>
          <span class="who">
            <span class="swatch" style="{p.ring ? `outline: 3px ${p.ring.dash ? 'dashed' : 'solid'} ${p.ring.color}; outline-offset: 1px;` : ''}"><Avatar name={p.name || ''} color={p.color} size={100} /></span>
            {cap(p.name)}
          </span>
          <span class="score">{p.score}</span>
        </li>
      {/each}
    </ul>
    <div class="actions">
      <button class="btn btn-start" onclick={again}>↻ Rematch</button>
      <button class="btn ghost" onclick={stopGame}>New game</button>
      <button class="btn ghost" onclick={undoWin}>↩ Undo last turn</button>
    </div>
  </div>
{/if}

<style>
  .section { background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); border-radius: 16px; padding: 1.5rem; margin-bottom: 1rem; }
  .heading { font-size: 1.6rem; font-weight: 800; color: var(--green); }
  .meta { color: var(--muted); font-size: 0.85rem; margin: 0.25rem 0 1rem; }
  .results { list-style: none; padding: 0; margin-bottom: 1.25rem; }
  .results li { display: grid; grid-template-columns: 2rem 1fr auto; gap: 0.75rem; align-items: center; padding: 0.55rem 0.8rem; margin-top: 0.5rem; border: 1px solid var(--glass-border); border-radius: 12px; background: rgba(0, 0, 0, 0.22); }
  .results li.winner { border-color: color-mix(in srgb, var(--green) 55%, transparent); }
  .place { color: var(--muted); font-weight: 700; }
  .who { display: flex; align-items: center; gap: 0.6rem; }
  .swatch { width: 1.7rem; height: 1.7rem; border-radius: 50%; flex-shrink: 0;  overflow: visible; }
  .score { font-weight: 800; }
  .actions { display: flex; gap: 0.6rem; flex-wrap: wrap; }
  .btn { border: none; border-radius: 8px; padding: 0.65rem 1.4rem; font-size: 0.95rem; font-weight: 600; cursor: pointer; }
  .btn-start { background: #166534; color: #fff; }
  .btn.ghost { background: var(--glass); color: color-mix(in srgb, var(--text) 82%, transparent); border: 1px solid var(--glass-border); }
  .btn.ghost:hover { border-color: var(--accent); color: var(--text); }
  .swatch :global(svg) { width: 100%; height: 100%; }
</style>
