<script>
  import { t } from '../../../lib/i18n.js';
  // How long games take, one row per lives setting. Every finished game is a
  // dot on a shared minutes axis and the average is a tick, so a handful of
  // games is shown as it is instead of being squeezed into one bar.
  import { cap } from '../../../lib/util.js';

  let { games = [] } = $props();

  const W = 700, LEFT = 70, RIGHT = 170, ROW = 54, TOP = 6, AXIS = 22, LANES = [0, -10, 10, -20, 20];
  const plotW = W - LEFT - RIGHT;

  let groups = $derived.by(() => {
    const byLives = new Map();
    for (const g of games) {
      if (!byLives.has(g.lives)) byLives.set(g.lives, []);
      byLives.get(g.lives).push(g);
    }
    return [...byLives.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([lives, list]) => ({
        lives, list,
        avg: list.reduce((s, g) => s + g.minutes, 0) / list.length,
      }));
  });

  // Many games in one row: smaller dots so they overlap less.
  let R = $derived(games.length > 30 ? 4 : 5);
  let longest = $derived(Math.max(0, ...games.map((g) => g.minutes)));
  let step = $derived(longest <= 6 ? 1 : longest <= 12 ? 2 : longest <= 30 ? 5 : 10);
  let axisMax = $derived(Math.max(step * 2, Math.ceil(longest / step) * step));
  let ticks = $derived(Array.from({ length: axisMax / step + 1 }, (_, i) => i * step));
  let height = $derived(TOP + groups.length * ROW + AXIS);

  const x = (minutes) => LEFT + (minutes / axisMax) * plotW;

  // Dots that would overlap go to a neighbouring lane instead of on top of each other.
  function placed(list) {
    const taken = [];
    return [...list].sort((a, b) => a.minutes - b.minutes).map((g) => {
      const cx = x(g.minutes);
      let lane = 0;
      while (lane < LANES.length - 1 && taken.some((tk) => tk.lane === lane && Math.abs(tk.cx - cx) < 2 * R + 1)) lane++;
      taken.push({ cx, lane });
      return { ...g, cx, dy: LANES[lane] };
    });
  }

  function describe(g) {
    const date = new Date(g.date).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
    return `${date} · ${g.minutes.toFixed(1)} ${t('min')} · ${t('{n} players', { n: g.size })}${g.winner ? ' · ' + t('won by {name}', { name: cap(g.winner) }) : ''}`;
  }
  const livesLabel = (n) => `${n} ${n === 1 ? t('life') : t('lives')}`;
</script>

{#if !groups.length}
  <div class="empty">{t('No finished games with a recorded length yet.')}</div>
{:else}
  <div class="legend">
    <span class="legend-item"><span class="dot"></span>{t('one game')}</span>
    <span class="legend-item"><span class="avg"></span>{t('average')}</span>
  </div>
  <svg viewBox="0 0 {W} {height}" class="chart" role="img"
       aria-label={t('Game length in minutes by lives setting')}>
    {#each ticks as tk}
      <line class="grid" x1={x(tk)} x2={x(tk)} y1={TOP} y2={TOP + groups.length * ROW} />
      <text class="tick" x={x(tk)} y={TOP + groups.length * ROW + 15} text-anchor="middle">{tk}{tk === axisMax ? ' ' + t('min') : ''}</text>
    {/each}
    {#each groups as g, i}
      {@const cy = TOP + i * ROW + ROW / 2}
      <text class="label" x={LEFT - 12} y={cy} text-anchor="end" dominant-baseline="central">{livesLabel(g.lives)}</text>
      <line class="avgline" x1={x(g.avg)} x2={x(g.avg)} y1={cy - 24} y2={cy + 24} />
      {#each placed(g.list) as d (d.match_id)}
        <circle class="game" cx={d.cx} cy={cy + d.dy} r={R}><title>{describe(d)}</title></circle>
      {/each}
      <text class="value" x={W - RIGHT + 14} y={cy} dominant-baseline="central">
        {g.list.length} {g.list.length === 1 ? t('game') : t('games')} · Ø {g.avg.toFixed(1)} {t('min')}
      </text>
    {/each}
  </svg>
{/if}

<style>
  .empty { color: var(--muted); text-align: center; padding: 1.5rem 0; }
  .legend { display: flex; flex-wrap: wrap; gap: 1rem; font-size: 0.75rem; color: var(--muted); margin-bottom: 0.4rem; }
  .legend-item { display: inline-flex; align-items: center; gap: 0.35rem; }
  .dot { width: 0.7rem; height: 0.7rem; border-radius: 50%; background: var(--accent); display: inline-block; }
  .avg { width: 2px; height: 0.95rem; background: var(--text); display: inline-block; }
  .chart { width: 100%; height: auto; display: block; }
  .grid { stroke: var(--border); stroke-width: 1; }
  .tick { fill: var(--muted); font-size: 11px; }
  .label { fill: var(--text); font-size: 13px; font-weight: 600; }
  .value { fill: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; }
  .avgline { stroke: var(--text); stroke-width: 2; }
  .game { fill: var(--accent); stroke: var(--surface); stroke-width: 2; }
</style>
