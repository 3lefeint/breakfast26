<script>
  import { t } from '../../../lib/i18n.js';
  // Warm-up half of the Stats tab: per player and per set of stations (never mixed) the complete runs, the fewest and
  // the average darts, how the darts of a run developed over time, the fields that needed the most darts on average
  // and the runs.
  import { cap } from '../../../lib/util.js';
  import { fieldLabel, modeLabel } from '../../../lib/warmUp.js';
  import TrendLine from './TrendLine.svelte';
  import RecentMatches from './RecentMatches.svelte';

  let data = $state(null);
  let loadFailed = $state(false);
  let playerName = $state(null);
  let modeKey = $state(null);

  $effect(() => {
    fetch('/api/stats/warm-up/overview')
      .then((r) => r.json())
      .then((body) => { data = body; })
      .catch(() => { loadFailed = true; });
  });

  let players = $derived(data?.players || []);
  let player = $derived(players.find((p) => p.player === playerName) || players[0] || null);
  let modes = $derived(player?.modes || []);
  let mode = $derived(modes.find((m) => m.key === modeKey) || modes[0] || null);
  let complete = $derived((mode?.runs || []).filter((r) => r.complete));
  let trend = $derived(complete.map((r) => ({
    value: r.darts, date: r.date, tip: t('{n} darts', { n: r.darts }),
  })));
  let recent = $derived([...(mode?.runs || [])].reverse().slice(0, 15));
  let last = $derived(complete.length ? complete[complete.length - 1].darts : null);

  function dateOf(d) { return new Date(d).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }); }
</script>

{#if loadFailed}
  <div class="empty">{t('Could not load stats.')}</div>
{:else if data && !players.length}
  <div class="empty">{t('No Warm-up runs yet.')}</div>
{:else if data && player && mode}
  {#if players.length > 1}
    <div class="picker" role="tablist" aria-label={t('Player')}>
      {#each players as p}
        <button type="button" class="pick" class:active={p.player === player.player}
                onclick={() => { playerName = p.player; modeKey = null; }}>{cap(p.player)}</button>
      {/each}
    </div>
  {/if}
  {#if modes.length > 1}
    <div class="picker" role="tablist" aria-label={t('Stations')}>
      {#each modes as m (m.key)}
        <button type="button" class="pick" class:active={m.key === mode.key}
                onclick={() => (modeKey = m.key)}>{modeLabel(m.kinds)}</button>
      {/each}
    </div>
  {/if}

  <div class="section-title">{cap(player.player)}</div>
  <div class="stat-tiles">
    <div class="stat-tile"><div class="stat-tile-label">{t('Runs')}</div><div class="stat-tile-value">{mode.runs.length}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">{t('Complete')}</div><div class="stat-tile-value">{mode.complete_runs}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">{t('Fewest darts')}</div><div class="stat-tile-value">{mode.fewest_darts ?? '—'}</div><div class="sub">{t('for all fields')}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">{t('Average darts')}</div><div class="stat-tile-value">{mode.average_darts ?? '—'}</div><div class="sub">{t('per complete run')}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">{t('Last run')}</div><div class="stat-tile-value">{last ?? '—'}</div><div class="sub">{t('darts')}</div></div>
  </div>

  {#if trend.length}
    <div class="section-title top">{t('Darts per complete run')}</div>
    <div class="card"><TrendLine points={trend} yTitle="Darts" decimals={0} width={680} /></div>
  {/if}

  {#if mode.slowest.length}
    <div class="section-title top">{t('Fields that needed the most darts')}</div>
    <div class="slow">
      {#each mode.slowest as f}
        <span class="chip">{fieldLabel(f.kind, f.number)} <b>{f.average}</b></span>
      {/each}
    </div>
  {/if}

  <div class="section-title top">{t('Runs')}</div>
  <table class="runs">
    <thead>
      <tr><th>{t('Date')}</th><th class="num">{t('Fields')}</th><th class="num">{t('Darts')}</th><th></th></tr>
    </thead>
    <tbody>
      {#each recent as r (r.match_id)}
        <tr>
          <td>{dateOf(r.date)}</td>
          <td class="num">{r.fields}/{r.total}</td>
          <td class="num">{r.darts}</td>
          <td class="num">{r.complete ? t('✓ Complete') : ''}</td>
        </tr>
      {/each}
    </tbody>
  </table>
{/if}

<RecentMatches mode="warm_up" />

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
  .slow { display: flex; flex-wrap: wrap; gap: 0.4rem; }
  .chip { border: 1px solid var(--glass-border); border-radius: 999px; padding: 0.15em 0.7em; font-size: 0.85rem; }
  .chip b { color: var(--accent); margin-left: 0.2em; }
  .runs { width: 100%; border-collapse: collapse; }
  .runs th { font-size: 0.75rem; color: var(--muted); font-weight: 500; text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid var(--glass-border); }
  .runs td { padding: 0.5rem 0.6rem; border-bottom: 1px solid var(--glass-border); font-size: 0.8rem; }
  .num { text-align: right; }
  .runs th.num { text-align: right; }
</style>
