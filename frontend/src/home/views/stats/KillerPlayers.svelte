<script>
  // Killer per player: how often they became a killer and how fast, what they took from others
  // (lives, knockouts), and what they lost (own goals, lives).
  import { cap } from '../../../lib/util.js';

  let { players = [] } = $props();

  let rows = $derived(players.filter((p) => p.games > 0));

  function num(v, digits = 1) { return v == null ? '—' : v.toFixed(digits); }
</script>

{#if !rows.length}
  <div class="empty">No finished Killer games yet.</div>
{:else}
  <table class="players-table">
    <thead>
      <tr>
        <th>Player</th><th class="num">Games</th><th class="num">Became killer</th><th class="num">Turns to killer</th>
        <th class="num">Lives taken</th><th class="num">Per game</th><th class="num">Knockouts</th>
        <th class="num">Own goals</th><th class="num">Lives lost</th>
      </tr>
    </thead>
    <tbody>
      {#each rows as p (p.player)}
        <tr>
          <td>{cap(p.player)}</td>
          <td class="num">{p.games}</td>
          <td class="num" title="{p.killer_games} of {p.games} games">{p.killer_pct != null ? p.killer_pct.toFixed(0) + '%' : '—'}</td>
          <td class="num" title={p.fastest_killer != null ? `fastest: ${p.fastest_killer}` : ''}>{num(p.avg_turns_to_killer)}</td>
          <td class="num">{p.lives_taken}</td>
          <td class="num">{num(p.lives_taken_per_game)}</td>
          <td class="num">{p.knockouts}</td>
          <td class="num">{p.own_goals}</td>
          <td class="num">{p.lives_lost}</td>
        </tr>
      {/each}
    </tbody>
  </table>
  <div class="note">Turns to killer count up to and including the turn that made the killer; a double thrown for the number counts as the first.</div>
{/if}

<style>
  .empty { color: var(--muted); text-align: center; padding: 1.5rem 0; }
  .players-table { width: 100%; border-collapse: collapse; }
  .players-table th { font-size: 0.75rem; color: var(--muted); font-weight: 500; text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid var(--border); }
  .players-table td { padding: 0.55rem 0.6rem; border-bottom: 1px solid var(--border); font-size: 0.85rem; }
  .num { text-align: right; }
  .players-table th.num { text-align: right; }
  .note { font-size: 0.7rem; color: var(--muted); margin-top: 0.4rem; }
</style>
