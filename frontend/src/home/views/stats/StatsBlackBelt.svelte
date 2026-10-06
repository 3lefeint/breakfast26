<script>
  import { t } from '../../../lib/i18n.js';
  // Black Belt half of the Stats tab: per player the belts earned, the furthest the player got, the
  // fewest darts for a belt, the average darts per run, how far each run got over time and the runs.
  import { cap } from '../../../lib/util.js';
  import TrendLine from './TrendLine.svelte';
  import RecentMatches from './RecentMatches.svelte';

  let data = $state(null);
  let loadFailed = $state(false);
  let playerName = $state(null);

  $effect(() => {
    fetch('/api/stats/black-belt/overview')
      .then((r) => r.json())
      .then((body) => { data = body; })
      .catch(() => { loadFailed = true; });
  });

  let players = $derived(data?.players || []);
  let player = $derived(players.find((p) => p.player === playerName) || players[0] || null);
  let trend = $derived((player?.runs || []).map((r) => ({
    value: r.furthest, date: r.date,
    tip: `${t('{n} of 21 fields', { n: r.furthest })} · ${t('{n} darts', { n: r.darts })} · ${t('{n} restarts', { n: r.restarts })}${r.belt ? ' · ' + t('belt') : ''}`,
  })));
  let recent = $derived([...(player?.runs || [])].reverse().slice(0, 15));

  function dateOf(d) { return new Date(d).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }); }
</script>

{#if loadFailed}
  <div class="empty">{t('Could not load stats.')}</div>
{:else if data && !players.length}
  <div class="empty">{t('No Black Belt runs yet.')}</div>
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
    <div class="stat-tile"><div class="stat-tile-label">{t('Runs')}</div><div class="stat-tile-value">{player.runs.length}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">{t('Belts')}</div><div class="stat-tile-value">{player.belts}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">{t('Furthest')}</div><div class="stat-tile-value">{player.furthest}</div><div class="sub">{t('of 21 fields')}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">{t('Fewest darts')}</div><div class="stat-tile-value">{player.fewest_darts ?? '—'}</div><div class="sub">{t('for a belt')}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">{t('Average darts')}</div><div class="stat-tile-value">{player.average_darts}</div><div class="sub">{t('per run')}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">{t('Restarts')}</div><div class="stat-tile-value">{player.restarts}</div><div class="sub">{t('all runs')}</div></div>
  </div>

  <div class="section-title top">{t('Fields done per run')}</div>
  <div class="card"><TrendLine points={trend} yTitle="Fields done" decimals={0} width={680} /></div>

  <div class="section-title top">{t('Runs')}</div>
  <table class="runs">
    <thead>
      <tr><th>{t('Date')}</th><th>{t('Ladder')}</th><th class="num">{t('Fields')}</th><th class="num">{t('Restarts')}</th><th class="num">{t('Darts')}</th><th></th></tr>
    </thead>
    <tbody>
      {#each recent as r (r.match_id)}
        <tr>
          <td>{dateOf(r.date)}</td>
          <td>{r.backwards ? 'D20 → D1' : 'D1 → D20'}</td>
          <td class="num">{r.furthest}</td>
          <td class="num">{r.restarts}</td>
          <td class="num">{r.darts}</td>
          <td class="num">{r.belt ? t('🥋 Belt') : ''}</td>
        </tr>
      {/each}
    </tbody>
  </table>
{/if}

<RecentMatches mode="black_belt" />

<style>
  .picker { display: flex; gap: 0.4rem; margin-bottom: 1rem; flex-wrap: wrap; }
  .pick {
    background: var(--glass); border: 1px solid var(--glass-border); color: var(--muted); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2);
    border-radius: 20px; padding: 0.3rem 0.9rem; font-family: inherit; font-size: 0.8rem; cursor: pointer;
  }
  .pick:hover { border-color: var(--accent); color: var(--text); }
  .pick.active { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); font-weight: 700; }
  .section-title { font-size: 0.8rem; color: var(--muted); margin: 0 0 0.6rem; letter-spacing: 0.06em; text-transform: uppercase; }
  .section-title.top { margin-top: 1.75rem; }
  .empty { color: var(--muted); text-align: center; padding: 1.5rem 0; }
  .stat-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 0.75rem; }
  .stat-tile { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 12px; box-shadow: var(--glass-shadow); padding: 0.75rem 0.9rem; text-align: center; }
  .stat-tile-label { font-size: 0.7rem; color: var(--muted); margin-bottom: 0.3rem; }
  .stat-tile-value { font-size: 1.4rem; font-weight: 600; }
  .sub { font-size: 0.7rem; color: var(--muted); margin-top: 0.2rem; }
  .card { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 14px; box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); padding: 0.75rem; }
  .runs { width: 100%; border-collapse: collapse; }
  .runs th { font-size: 0.75rem; color: var(--muted); font-weight: 500; text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid var(--glass-border); }
  .runs td { padding: 0.5rem 0.6rem; border-bottom: 1px solid var(--glass-border); font-size: 0.8rem; }
  .num { text-align: right; }
  .runs th.num { text-align: right; }
</style>
