<script>
  import { t } from '../../lib/i18n.js';
  import Avatar from '../../lib/components/Avatar.svelte';
  // The result of a finished Target Battle on the TV: the placements with their scores, the winners
  // marked with the crown, and the table of every round. Players who tied share a placement and all win.
  import { cap } from '../../lib/util.js';
  import { api } from '../../lib/api.js';
  import { rematch, stopGame } from '../../lib/targetBattle.js';
  import Crown from '../../lib/components/Crown.svelte';
  import ConfettiBurst from '../../lib/components/ConfettiBurst.svelte';

  let { tb } = $props();

  let rows = $derived([...(tb.players || [])].sort((a, b) => a.placement - b.placement || b.score - a.score));
  let solo = $derived((tb.players || []).length === 1);
  let history = $derived(tb.history || []);
  let heading = $derived(
    solo ? t('Finished') : tb.winners.length > 1 ? t('{names} win', { names: tb.winners.map(cap).join(t(' and ')) }) : t('{name} wins', { name: cap(tb.winners[0] || '') })
  );

  async function undo() {
    if (!confirm(t('Undo the last turn and resume the game?'))) return;
    await api('POST', '/api/target-battle/undo');
  }

  async function done() {
    await stopGame();
    window.location.href = '/#target-battle';
  }
</script>

{#if !solo}<ConfettiBurst />{/if}

<div class="finished">
  <div class="heading">{heading}</div>
  <ul class="results">
    {#each rows as p (p.name)}
      <li class:winner={tb.winners.includes(p.name)}>
        <span class="place">{p.placement}</span>
        <span class="who">
          <span class="swatch" style="{p.ring ? `outline: 3px ${p.ring.dash ? 'dashed' : 'solid'} ${p.ring.color}; outline-offset: 1px;` : ''}"><Avatar name={p.name || ''} color={p.color} size={100} /></span>
          <span class="name-crown">{#if tb.winners.includes(p.name)}<Crown />{/if}{cap(p.name)}</span>
        </span>
        <span class="score">{p.score}</span>
      </li>
    {/each}
  </ul>
  <div class="history">
    <table>
      <thead>
        <tr>
          <th>{t('Round')}</th><th>{t('Target')}</th>
          {#each rows as p}<th class="player">{cap(p.name)}</th>{/each}
        </tr>
      </thead>
      <tbody>
        {#each history as r (`${r.tiebreak ? 't' : 'r'}${r.round}`)}
          <tr>
            <td>{r.tiebreak ? `T${r.round}` : r.round}</td>
            <td class="t">{r.target}</td>
            {#each rows as p}<td class:zero={r.scores[p.name] === 0}>{r.scores[p.name] ?? '—'}</td>{/each}
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
  <div class="actions">
    <button class="btn" onclick={() => rematch(tb)}>{t('↻ Rematch')}</button>
    <button class="btn ghost" onclick={undo}>{t('↩ Undo last turn')}</button>
    <button class="btn ghost" onclick={done}>{t('Done')}</button>
  </div>
</div>

<style>
  .finished { flex: 1; min-height: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 1.6rem; padding: 1.5rem 2rem; }
  .heading { font-size: clamp(2rem, 5vw, 4.2rem); font-weight: 800; color: var(--green); text-align: center; }
  .results { list-style: none; padding: 0; width: min(36rem, 90vw); }
  .results li {
    display: grid; grid-template-columns: 2.5rem 1fr auto; align-items: center; gap: 1rem;
    padding: 0.7rem 1.2rem; margin-top: 0.7rem; border-radius: 16px;
    background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); font-size: clamp(1.1rem, 2.4vw, 2rem);
  }
  .results li.winner { border-color: color-mix(in srgb, var(--green) 55%, transparent); }
  .place { color: var(--muted); font-weight: 700; }
  .who { display: flex; align-items: center; gap: 0.7em; }
  .name-crown { position: relative; display: inline-block; }
  .swatch { width: 1.5em; height: 1.5em; border-radius: 50%; flex-shrink: 0;  overflow: visible; }
  .score { font-weight: 800; }
  .history { width: min(36rem, 90vw); max-height: 30vh; overflow-y: auto; border: 1px solid var(--glass-border); border-radius: 12px; background: rgba(0, 0, 0, 0.22); }
  table { width: 100%; border-collapse: collapse; font-size: clamp(0.85rem, 1.4vw, 1.4rem); }
  th { position: sticky; top: 0; background: color-mix(in srgb, var(--aurora-base) 85%, transparent); color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; font-size: 0.75em; padding: 0.5em 0.6em; text-align: center; }
  th.player { max-width: 6em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  td { padding: 0.35em 0.6em; text-align: center; border-top: 1px solid var(--glass-border); }
  td.t { color: var(--accent); font-weight: 800; }
  td.zero { color: var(--muted); }
  .actions { display: flex; gap: 0.8rem; flex-wrap: wrap; justify-content: center; }
  .btn { background: #166534; color: #fff; border: none; border-radius: 999px; padding: 0.7rem 1.6rem; font-size: 1rem; font-weight: 600; cursor: pointer; }
  .btn.ghost { background: var(--glass); color: color-mix(in srgb, var(--text) 82%, transparent); border: 1px solid var(--glass-border); }
  .btn.ghost:hover { border-color: var(--accent); color: var(--text); }
  .swatch :global(svg) { width: 100%; height: 100%; }
</style>
