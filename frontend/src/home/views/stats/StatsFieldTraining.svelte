<script>
  import { t } from '../../../lib/i18n.js';
  // Field Training half of the Stats tab: per player and field the best and the average points of
  // the runs that count, the trend over those runs, the hit rate, where the darts landed and the
  // runs themselves. Points are on the scale of the standard length (100 darts at a number, 50 at
  // the bull), so runs of another length can be compared.
  import { cap } from '../../../lib/util.js';
  import { fieldLabel, RATING_LABELS, percent } from '../../../lib/fieldTraining.js';
  import TrendLine from './TrendLine.svelte';
  import PositionHeatmap from './PositionHeatmap.svelte';
  import RecentMatches from './RecentMatches.svelte';

  let data = $state(null);
  let loadFailed = $state(false);
  let playerName = $state(null);
  let fieldNumber = $state(null);

  $effect(() => {
    fetch('/api/stats/field-training/overview')
      .then((r) => r.json())
      .then((body) => { data = body; })
      .catch(() => { loadFailed = true; });
  });

  let players = $derived(data?.players || []);
  let player = $derived(players.find((p) => p.player === playerName) || players[0] || null);
  let field = $derived(player?.fields.find((f) => f.field === fieldNumber) || player?.fields[0] || null);
  let counted = $derived((field?.runs || []).filter((r) => r.counts));
  let trend = $derived(counted.map((r) => ({
    value: r.scaled_points, date: r.date,
    tip: t('{points} points in {darts} darts · {rate} hit rate', { points: r.points, darts: r.darts, rate: percent(r.hit_rate) }),
  })));
  let recent = $derived([...(field?.runs || [])].reverse().slice(0, 15));
  let latest = $derived(counted.length ? counted[counted.length - 1] : null);

  function dateOf(d) { return new Date(d).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }); }
</script>

{#if loadFailed}
  <div class="empty">{t('Could not load stats.')}</div>
{:else if data && !players.length}
  <div class="empty">{t('No Field Training runs yet.')}</div>
{:else if data && player && field}
  {#if players.length > 1}
    <div class="picker" role="tablist" aria-label={t('Player')}>
      {#each players as p}
        <button type="button" class="pick" class:active={p.player === player.player}
                onclick={() => { playerName = p.player; fieldNumber = null; }}>{cap(p.player)}</button>
      {/each}
    </div>
  {/if}
  <div class="picker" role="tablist" aria-label={t('Field')}>
    {#each player.fields as f}
      <button type="button" class="pick" class:active={f.field === field.field}
              onclick={() => (fieldNumber = f.field)}>{fieldLabel(f.field)}</button>
    {/each}
  </div>

  <div class="section-title">{cap(player.player)} · {fieldLabel(field.field)}</div>
  <div class="stat-tiles">
    <div class="stat-tile"><div class="stat-tile-label">{t('Runs')}</div>
      <div class="stat-tile-value">{field.runs.length}</div>
      <div class="sub">{t('{counted} counted · {practice} practice', { counted: field.counted, practice: field.practice })}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">{t('Best')}</div>
      <div class="stat-tile-value">{field.best ?? '—'}</div>
      <div class="sub">{t('per {n} darts', { n: field.standard_darts })}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">{t('Average')}</div>
      <div class="stat-tile-value">{field.average ?? '—'}</div>
      <div class="sub">{t('per {n} darts', { n: field.standard_darts })}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">{t('Hit rate')}</div>
      <div class="stat-tile-value">{percent(field.hit_rate)}</div>
      <div class="sub">{t('all darts')}</div></div>
    <div class="stat-tile"><div class="stat-tile-label">{t('Latest rating')}</div>
      <div class="stat-tile-value">{latest?.rating ? RATING_LABELS[latest.rating] : '—'}</div>
      <div class="sub">{latest ? dateOf(latest.date) : ''}</div></div>
  </div>

  <div class="section-title top">{t('Points per run')}</div>
  <div class="card"><TrendLine points={trend} yTitle="Points per {field.standard_darts} darts" decimals={1} width={680} /></div>

  <div class="section-title top">{t('Where the darts landed')}</div>
  <div class="card heat"><PositionHeatmap darts={field.positions.darts} corrected={field.positions.corrected} /></div>

  <div class="section-title top">{t('Runs')}</div>
  <table class="runs">
    <thead>
      <tr><th>{t('Date')}</th><th class="num">{t('Darts')}</th><th class="num">{t('Points')}</th><th class="num">{t('Per {n}', { n: field.standard_darts })}</th><th class="num">{t('Hit rate')}</th><th></th></tr>
    </thead>
    <tbody>
      {#each recent as r (r.match_id)}
        <tr>
          <td>{dateOf(r.date)}</td>
          <td class="num">{r.darts}</td>
          <td class="num">{r.points}</td>
          <td class="num">{r.counts ? r.scaled_points : '—'}</td>
          <td class="num">{percent(r.hit_rate)}</td>
          <td class="num">{r.counts ? RATING_LABELS[r.rating] : t('Practice')}</td>
        </tr>
      {/each}
    </tbody>
  </table>
{/if}

<RecentMatches mode="field_training" />

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
  .sub { font-size: 0.7rem; color: var(--muted); margin-top: 0.2rem; min-height: 1.1em; }
  .card { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 14px; box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); padding: 0.75rem; }
  .card.heat { display: flex; justify-content: center; }
  .runs { width: 100%; border-collapse: collapse; }
  .runs th { font-size: 0.75rem; color: var(--muted); font-weight: 500; text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid var(--glass-border); }
  .runs td { padding: 0.5rem 0.6rem; border-bottom: 1px solid var(--glass-border); font-size: 0.8rem; }
  .num { text-align: right; }
  .runs th.num { text-align: right; }
</style>
