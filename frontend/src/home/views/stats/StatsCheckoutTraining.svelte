<script>
  import { t } from '../../../lib/i18n.js';
  // Random checkout half of the Stats tab: per player how often an attempt worked overall and by
  // range of scores, which scores work and which do not (with the standard route to practise), and
  // the runs themselves.
  import { cap } from '../../../lib/util.js';
  import { percent, rangeLabel } from '../../../lib/checkoutTraining.js';
  import RouteChips from '../../../lib/components/RouteChips.svelte';
  import RecentMatches from './RecentMatches.svelte';

  let data = $state(null);
  let loadFailed = $state(false);
  let playerName = $state(null);

  $effect(() => {
    fetch('/api/stats/checkout-training/overview')
      .then((r) => r.json())
      .then((body) => { data = body; })
      .catch(() => { loadFailed = true; });
  });

  let players = $derived(data?.players || []);
  let player = $derived(players.find((p) => p.player === playerName) || players[0] || null);
  let recent = $derived([...(player?.runs || [])].reverse().slice(0, 15));

  function dateOf(d) { return new Date(d).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }); }
  const tone = (rate) => (rate >= 0.7 ? 'strong' : rate >= 0.4 ? 'ok' : 'weak');
</script>

{#if loadFailed}
  <div class="empty">{t('Could not load stats.')}</div>
{:else if data && !players.length}
  <div class="empty">{t('No Checkout Training runs yet.')}</div>
{:else if data && player}
  {#if players.length > 1}
    <div class="picker" role="tablist" aria-label={t('Player')}>
      {#each players as p}
        <button type="button" class="pick" class:active={p.player === player.player}
                onclick={() => (playerName = p.player)}>{cap(p.player)}</button>
      {/each}
    </div>
  {/if}

  <div class="section-title">{cap(player.player)}</div>
  <div class="stat-tiles">
    <div class="stat-tile"><div class="stat-tile-label">{t('Attempts')}</div>
      <div class="stat-tile-value">{player.attempts}</div>
      <div class="sub">{player.runs.length === 1 ? t('{n} run', { n: 1 }) : t('{n} runs', { n: player.runs.length })}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">{t('Worked')}</div>
      <div class="stat-tile-value">{player.successes}</div>
      <div class="sub">{t('finished on a double')}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">{t('Success rate')}</div>
      <div class="stat-tile-value">{percent(player.rate)}</div>
      <div class="sub">{t('all attempts')}</div></div>
  </div>

  <div class="section-title top">{t('By range of scores')}</div>
  <div class="card ranges">
    {#each player.by_range as r}
      <div class="range-row">
        <span class="range-name">{rangeLabel(r.low, r.high)}</span>
        <span class="bar"><span class="fill" style="width: {(r.rate || 0) * 100}%"></span></span>
        <span class="range-val">{r.attempts ? `${percent(r.rate)} · ${r.successes}/${r.attempts}` : '—'}</span>
      </div>
    {/each}
  </div>

  <div class="section-title top">{t('Weakest scores')}</div>
  {#if player.weakest.length}
    <table class="runs">
      <thead><tr><th>{t('Score')}</th><th>{t('Standard route')}</th><th class="num">{t('Worked')}</th></tr></thead>
      <tbody>
        {#each player.weakest as w (w.score)}
          <tr><td class="score">{w.score}</td><td><RouteChips route={w.route} /></td><td class="num">{w.successes} / {w.attempts}</td></tr>
        {/each}
      </tbody>
    </table>
  {:else}
    <div class="empty">{t('Every score you tried worked.')}</div>
  {/if}

  <div class="section-title top">{t('Every score tried')}</div>
  <div class="grid">
    {#each player.by_score as s (s.score)}
      <span class="cell {tone(s.rate)}" title={t('{score}: {worked} of {tried} worked', { score: s.score, worked: s.successes, tried: s.attempts })}>{s.score}</span>
    {/each}
  </div>

  <div class="section-title top">{t('Runs')}</div>
  <table class="runs">
    <thead><tr><th>{t('Date')}</th><th>{t('Scores')}</th><th class="num">{t('Attempts')}</th><th class="num">{t('Worked')}</th><th class="num">{t('Success rate')}</th></tr></thead>
    <tbody>
      {#each recent as r (r.match_id)}
        <tr>
          <td>{dateOf(r.date)}</td>
          <td>{rangeLabel(r.low, r.high)}</td>
          <td class="num">{r.attempts}</td>
          <td class="num">{r.successes}</td>
          <td class="num">{percent(r.rate)}{r.completed ? '' : ' *'}</td>
        </tr>
      {/each}
    </tbody>
  </table>
{/if}

<RecentMatches mode="checkout_training" />

<style>
  .picker { display: flex; gap: 0.4rem; margin-bottom: 1rem; flex-wrap: wrap; }
  .pick { background: var(--glass); border: 1px solid var(--glass-border); color: var(--muted); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2); border-radius: 20px; padding: 0.3rem 0.9rem; font-family: inherit; font-size: 0.8rem; cursor: pointer; }
  .pick:hover { border-color: var(--accent); color: var(--text); }
  .pick.active { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); font-weight: 700; }
  .section-title { font-size: 0.8rem; color: var(--muted); margin: 0 0 0.6rem; letter-spacing: 0.06em; text-transform: uppercase; }
  .section-title.top { margin-top: 1.75rem; }
  .empty { color: var(--muted); text-align: center; padding: 1.5rem 0; }
  .stat-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 0.75rem; }
  .stat-tile { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 12px; box-shadow: var(--glass-shadow); padding: 0.75rem 0.9rem; text-align: center; }
  .stat-tile-label { font-size: 0.7rem; color: var(--muted); margin-bottom: 0.3rem; }
  .stat-tile-value { font-size: 1.4rem; font-weight: 600; }
  .sub { font-size: 0.7rem; color: var(--muted); margin-top: 0.2rem; min-height: 1.1em; }
  .card { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 14px; box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); padding: 0.9rem 1rem; }
  .ranges { display: flex; flex-direction: column; gap: 0.7rem; }
  .range-row { display: grid; grid-template-columns: 6rem 1fr 9rem; gap: 0.8rem; align-items: center; font-size: 0.85rem; }
  .range-name { font-weight: 700; }
  .bar { height: 0.7rem; background: rgba(255, 255, 255, 0.12); border-radius: 999px; overflow: hidden; }
  .fill { display: block; height: 100%; background: var(--accent); border-radius: 999px; }
  .range-val { color: var(--muted); text-align: right; }
  .grid { display: flex; flex-wrap: wrap; gap: 0.3rem; }
  .cell { min-width: 2.4rem; text-align: center; padding: 0.25rem 0.3rem; border-radius: 8px; font-size: 0.8rem; font-weight: 700; border: 1px solid var(--glass-border); background: var(--glass); }
  .cell.strong { border-color: var(--green); color: var(--green); }
  .cell.ok { border-color: var(--accent); color: var(--accent); }
  .cell.weak { border-color: var(--red); color: var(--red); }
  .runs { width: 100%; border-collapse: collapse; }
  .runs th { font-size: 0.75rem; color: var(--muted); font-weight: 500; text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid var(--glass-border); }
  .runs td { padding: 0.5rem 0.6rem; border-bottom: 1px solid var(--glass-border); font-size: 0.8rem; }
  .runs .score { font-weight: 900; font-size: 0.95rem; }
  .num { text-align: right; }
  .runs th.num { text-align: right; }
</style>
