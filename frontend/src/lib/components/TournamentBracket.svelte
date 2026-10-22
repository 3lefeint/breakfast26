<script>
  import { t } from '../i18n.js';
  // The bracket of a tournament: one column per round, a card per match with both players. The winner of
  // a match is marked, the match in play and the pairing that is next are outlined. A seat without a
  // player is a bye.
  import { shownName } from '../util.js';
  import { roundName, legsLabel } from '../tournament.js';

  // `editable`: the seats of the first round can be clicked (`onSeat(seat)`, `picked` is the one that is selected),
  // for the setup page.
  let { snap, editable = false, picked = null, onSeat = () => {} } = $props();

  let rounds = $derived(snap?.rounds || []);
  let legs = $derived(snap?.config?.legs_by_round || []);
  let current = $derived(snap?.current || null);
  let next = $derived(snap?.next || null);
  let pending = $derived(snap?.pending || null);

  function kind(r, i) {
    if (current && current.round === r && current.index === i) return 'live';
    if (!current && next && next.round === r && next.index === i) return 'next';
    return '';
  }

  // The winner as far as the bracket knows: a recorded one, or the one whose match is won and waits.
  function winnerOf(r, i, m) {
    if (m.winner) return m.winner;
    return pending && pending.round === r && pending.index === i ? pending.winner : null;
  }

  function legsOf(m, name) {
    return m.legs && m.legs[name] != null ? m.legs[name] : '';
  }
</script>

<div class="bracket">
  {#each rounds as matches, r (r)}
    <div class="round">
      <div class="round-title">{roundName(r, rounds.length)}<span class="legs">{legsLabel(legs[r] || 1)}</span></div>
      <div class="matches">
        {#each matches as m, i (i)}
          {@const win = winnerOf(r, i, m)}
          <div class="match {kind(r, i)}" class:bye={m.bye}>
            {#each [m.a, m.b] as name, side}
              {#if editable && r === 0}
                <button type="button" class="seat clickable" class:picked={picked === 2 * i + side} class:empty={!name}
                        onclick={() => onSeat(2 * i + side)}>
                  <span class="name">{name ? shownName(name) : t('Bye')}</span>
                </button>
              {:else}
                <div class="seat" class:winner={win && name === win} class:lost={win && name && name !== win} class:empty={!name}>
                  <span class="name">{#if name}{shownName(name)}{:else if m.bye || r === 0}{t('Bye')}{:else}…{/if}</span>
                  <span class="score">{name ? legsOf(m, name) : ''}</span>
                </div>
              {/if}
            {/each}
          </div>
        {/each}
      </div>
    </div>
  {/each}
</div>

<style>
  .bracket { display: flex; gap: clamp(0.8rem, 2vw, 2.5rem); align-items: stretch; overflow-x: auto; padding: 0.3rem 0.1rem 0.6rem; }
  .round { display: flex; flex-direction: column; min-width: clamp(9rem, 16vw, 15rem); flex: 1 1 0; }
  .round-title { font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 0.6rem; display: flex; flex-direction: column; gap: 0.1rem; }
  .legs { font-size: 0.72rem; letter-spacing: normal; text-transform: none; font-weight: 400; }
  .matches { flex: 1; display: flex; flex-direction: column; justify-content: space-around; gap: 0.6rem; }
  .match {
    border-radius: 12px; overflow: hidden; background: var(--glass); border: 1px solid var(--glass-border);
    box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur);
  }
  .match.live { border-color: var(--green); box-shadow: 0 0 0 1px var(--green), var(--glass-shadow); }
  .match.next { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent), var(--glass-shadow); }
  .match.bye { opacity: 0.6; }
  .seat { display: flex; justify-content: space-between; gap: 0.8rem; padding: 0.45rem 0.8rem; font-size: clamp(0.85rem, 1.3vw, 1.3rem); width: 100%; box-sizing: border-box; background: none; border: none; color: inherit; font-family: inherit; text-align: left; }
  .seat.clickable { cursor: pointer; }
  .seat.clickable:hover { background: color-mix(in srgb, var(--accent) 12%, transparent); }
  .seat.picked { color: var(--yellow); background: color-mix(in srgb, var(--yellow) 14%, transparent); }
  .seat + .seat { border-top: 1px solid var(--glass-border); }
  .seat.winner { color: var(--green); font-weight: 700; background: color-mix(in srgb, var(--green) 10%, transparent); }
  .seat.lost { color: var(--muted); }
  .seat.empty { color: var(--muted); font-style: italic; }
  .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .score { font-weight: 700; min-width: 1ch; text-align: right; }
</style>
