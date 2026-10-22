<script>
  import { t } from '../../lib/i18n.js';
  // The summary of a finished X01 match: a header with the legs won, and three tabs: the figures of all
  // players side by side with the highlights, the legs (the course of the remaining score and every
  // turn next to the others) and the darts on the board. Used on the TV after a match and as a dialog
  // from the match list of the statistics.
  import { shownName, formatDateTime } from '../../lib/util.js';
  import Crown from './Crown.svelte';
  import { saveSummaryImage } from '../summaryImage.js';
  import { alertDialog } from '../confirm.js';
  import PositionHeatmap from '../../home/views/stats/PositionHeatmap.svelte';

  let { matchId } = $props();

  let summary = $state(null);
  let failed = $state(false);
  let tab = $state('overview');
  let leg = $state(1);

  $effect(() => {
    summary = null;
    failed = false;
    tab = 'overview';
    fetch(`/api/stats/x01/match/${encodeURIComponent(matchId)}/summary`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((data) => {
        summary = data;
        leg = data.legs.length ? data.legs[0].leg : 1;
      })
      .catch(() => (failed = true));
  });

  const PALETTE = ['#8bc34a', '#4aa3ff', '#ff9f43', '#c77dff', '#ff6b81', '#2ed3c6', '#ffd43b', '#9aa5b1'];
  let players = $derived((summary?.players || []).map((p, i) => ({ ...p, tint: p.color || PALETTE[i % PALETTE.length] })));
  let legsWon = $derived(Object.fromEntries(players.map((p) => [p.name, (summary?.legs || []).filter((l) => l.winner === p.name).length])));

  let played = $derived.by(() => {
    if (!summary?.started_at || !summary?.ended_at) return '';
    const min = Math.round((new Date(summary.ended_at) - new Date(summary.started_at)) / 60000);
    return min >= 60 ? `${Math.floor(min / 60)} h ${min % 60} min` : `${min} min`;
  });

  const fmt = (v, d = 1) => (v == null ? '—' : Number(v).toFixed(d));
  // One row per figure; `best` says which value stands out, `bar` draws a thin bar under it.
  let rows = $derived([
    { label: t('Average'), get: (p) => p.avg3, show: (p) => fmt(p.avg3), best: 'max', bar: true },
    { label: t('First 9 Dart Average'), get: (p) => p.first9, show: (p) => fmt(p.first9), best: 'max', bar: true },
    { label: t('Checkout %'), get: (p) => p.co_pct, show: (p) => (p.co_pct == null ? '—' : `${fmt(p.co_pct)}% (${p.co_hits}/${p.co_attempts})`), best: 'max', bar: true },
    { label: t('Darts thrown'), get: (p) => p.darts_thrown, show: (p) => p.darts_thrown },
    { label: '60+', get: (p) => p.s60, show: (p) => p.s60, best: 'max' },
    { label: '100+', get: (p) => p.s100, show: (p) => p.s100, best: 'max' },
    { label: '140+', get: (p) => p.s140, show: (p) => p.s140, best: 'max' },
    { label: '180', get: (p) => p.s180, show: (p) => p.s180, best: 'max' },
    { label: t('Busts'), get: (p) => p.busts, show: (p) => p.busts, best: 'min' },
  ]);
  function isBest(row, p) {
    if (!row.best || players.length < 2) return false;
    const values = players.map(row.get).filter((v) => v != null);
    const top = row.best === 'max' ? Math.max(...values) : Math.min(...values);
    return row.get(p) === top && new Set(values).size > 1;
  }
  const barWidth = (row, p) => {
    const max = Math.max(...players.map((q) => row.get(q) || 0));
    return max > 0 ? ((row.get(p) || 0) / max) * 100 : 0;
  };

  // The best of each kind across the players, as a few lines under the table.
  let highlights = $derived.by(() => {
    const best = (key, pick) => {
      const have = players.filter((p) => p[key] != null && p[key] > 0);
      if (!have.length) return null;
      const top = pick(...have.map((p) => p[key]));
      return { value: top, names: have.filter((p) => p[key] === top).map((p) => p.name) };
    };
    return [
      { label: t('Highest turn'), ...best('highest_turn', Math.max) },
      { label: t('Highest checkout'), ...best('highest_finish', Math.max) },
      { label: t('Fastest leg'), ...best('best_leg_darts', Math.min), unit: t('darts') },
    ].filter((h) => h.names);
  });

  async function saveImage() {
    try {
      await saveSummaryImage({ summary, players, legsWon, played, rows, isBest, barWidth, highlights });
    } catch (e) {
      alertDialog(t('The image could not be created.'));
    }
  }

  // The legs tab.
  const W = 720, H = 150, LEFT = 34, RIGHT = 8, TOP = 8, BOTTOM = 6;
  let turnsOfLeg = $derived((summary?.turns || []).filter((x) => x.leg === leg));
  // A smooth path through the points that never overshoots between them (monotone cubic, as d3's curveMonotoneX).
  function smooth(pts) {
    const n = pts.length;
    if (n < 3) return pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ');
    const dx = [], slope = [];
    for (let i = 0; i < n - 1; i++) {
      dx.push(pts[i + 1][0] - pts[i][0]);
      slope.push((pts[i + 1][1] - pts[i][1]) / dx[i]);
    }
    const m = [slope[0]];
    for (let i = 1; i < n - 1; i++) m.push(slope[i - 1] * slope[i] <= 0 ? 0 : (slope[i - 1] + slope[i]) / 2);
    m.push(slope[n - 2]);
    for (let i = 0; i < n - 1; i++) {
      if (slope[i] === 0) { m[i] = 0; m[i + 1] = 0; continue; }
      const a = m[i] / slope[i], b = m[i + 1] / slope[i], h = a * a + b * b;
      if (h > 9) { const k = 3 / Math.sqrt(h); m[i] = k * a * slope[i]; m[i + 1] = k * b * slope[i]; }
    }
    let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
    for (let i = 0; i < n - 1; i++) {
      const x1 = pts[i][0] + dx[i] / 3, x2 = pts[i + 1][0] - dx[i] / 3;
      d += ` C${x1.toFixed(1)},${(pts[i][1] + m[i] * dx[i] / 3).toFixed(1)} ${x2.toFixed(1)},${(pts[i + 1][1] - m[i + 1] * dx[i] / 3).toFixed(1)} ${pts[i + 1][0].toFixed(1)},${pts[i + 1][1].toFixed(1)}`;
    }
    return d;
  }
  function line(player) {
    const own = turnsOfLeg.filter((x) => x.player === player);
    if (!own.length) return null;
    const longest = Math.max(...players.map((p) => turnsOfLeg.filter((x) => x.player === p.name).length));
    const points = [own[0].remaining_before, ...own.map((x) => x.remaining)];
    const px = (i) => LEFT + (i / Math.max(1, longest)) * (W - LEFT - RIGHT);
    const py = (v) => TOP + (1 - v / summary.points_start) * (H - TOP - BOTTOM);
    return smooth(points.map((v, i) => [px(i), py(v)]));
  }
  const tickY = (v) => TOP + (1 - v / (summary?.points_start || 1)) * (H - TOP - BOTTOM);
  // One line per 100 points from 0 up to the start score.
  let ticks = $derived(summary ? Array.from({ length: Math.floor(summary.points_start / 100) + 1 }, (_, i) => i * 100) : []);
  let starter = $derived(turnsOfLeg[0]?.player);
  let turnNumbers = $derived(Array.from({ length: Math.max(0, ...turnsOfLeg.map((x) => x.turn)) }, (_, i) => i + 1));
  const turnOf = (player, n) => turnsOfLeg.find((x) => x.player === player && x.turn === n);
</script>

{#if failed}
  <div class="empty">{t('The summary could not be loaded.')}</div>
{:else if !summary}
  <div class="empty">{t('Loading…')}</div>
{:else}
  <div class="summary">
    <div class="meta">
      <span class="chip">X01</span><span class="chip">{summary.points_start}</span>
      <span class="when">{summary.started_at ? formatDateTime(summary.started_at) : ''}{played ? ` · ${played}` : ''}</span>
      <button type="button" class="save" onclick={saveImage}>{t('Export image')}</button>
    </div>

    <div class="scoreband">
      {#each players as p (p.name)}
        <div class="side" class:winner={p.name === summary.winner} style="--tint:{p.tint}">
          <div class="who"><span class="name-crown">{#if p.name === summary.winner}<Crown />{/if}{shownName(p.name)}</span></div>
          <div class="legs">{legsWon[p.name]}</div>
        </div>
      {/each}
    </div>

    <div class="tabs" role="tablist">
      {#each [['overview', t('Overview')], ['legs', t('Legs')], ['heat', t('Heatmaps')]] as [id, label]}
        <button type="button" role="tab" aria-selected={tab === id} class:on={tab === id} onclick={() => (tab = id)}>{label}</button>
      {/each}
    </div>

    {#if tab === 'overview'}
      <div class="compare" style="--cols:{players.length}">
        <div class="row head"><span></span>{#each players as p (p.name)}<span class="cell" style="color:{p.tint}">{shownName(p.name)}</span>{/each}</div>
        {#each rows as row (row.label)}
          <div class="row">
            <span class="label">{row.label}</span>
            {#each players as p (p.name)}
              <span class="cell">
                <b class:best={isBest(row, p)}>{row.show(p)}</b>
                {#if row.bar}<i class="bar"><i style="width:{barWidth(row, p)}%;background:{p.tint}"></i></i>{/if}
              </span>
            {/each}
          </div>
        {/each}
      </div>
      {#if highlights.length}
        <div class="highlights">
          {#each highlights as h (h.label)}
            <div class="hl"><span class="hl-label">{h.label}</span><b>{h.value}{#if h.unit}{' '}{h.unit}{/if}</b><span class="hl-who">{h.names.map(shownName).join(', ')}</span></div>
          {/each}
        </div>
      {/if}
    {:else if tab === 'legs'}
      <div class="legchips">
        {#each summary.legs as l (l.leg)}
          <button type="button" class:on={leg === l.leg} onclick={() => (leg = l.leg)}>{t('Leg {n}', { n: l.leg })}{#if l.winner}{' · '}{shownName(l.winner)}{/if}</button>
        {/each}
      </div>
      <svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label={t('Remaining score per turn')}>
        {#each ticks as v}
          <line x1={LEFT} x2={W - RIGHT} y1={tickY(v)} y2={tickY(v)} class="grid" />
          <text x={LEFT - 5} y={tickY(v) + 4} text-anchor="end" class="tick">{v}</text>
        {/each}
        {#each players as p (p.name)}
          {@const d = line(p.name)}
          {#if d}<path {d} fill="none" stroke={p.tint} stroke-width="2" stroke-linejoin="round" />{/if}
        {/each}
      </svg>
      <div class="turns" style="--cols:{players.length}">
        <div class="trow thead"><span></span>{#each players as p (p.name)}<span style="color:{p.tint}">{shownName(p.name)}{#if p.name === starter}<small class="starts">{t('Opener')}</small>{/if}</span>{/each}</div>
        {#each turnNumbers as n (n)}
          <div class="trow">
            <span class="n">{n}</span>
            {#each players as p (p.name)}
              {@const r = turnOf(p.name, n)}
              <span class="tcell" class:bust={r?.is_bust}>
                {#if r}<b>{r.is_bust ? t('Bust') : r.score}</b><em>{r.fields.join('  ')}</em>{/if}
              </span>
            {/each}
          </div>
        {/each}
      </div>
    {:else}
      <div class="heat">
        {#each players as p (p.name)}
          <section>
            <div class="hwho" style="color:{p.tint}">{shownName(p.name)}</div>
            <PositionHeatmap darts={p.darts} caption={false} />
          </section>
        {/each}
      </div>
    {/if}
  </div>
{/if}

<style>
  .empty { color: var(--muted); text-align: center; padding: 1.5rem 0; }
  .summary { display: flex; flex-direction: column; gap: 1rem; text-align: left; }
  .meta { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
  .chip { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 999px; padding: 0.15rem 0.8rem; font-weight: 700; font-size: 0.9rem; }
  .when { color: var(--muted); font-size: 0.9rem; margin-left: 0.4rem; }
  .save { margin-left: auto; background: var(--glass); border: 1px solid var(--glass-border); border-radius: 999px; padding: 0.4rem 1.1rem; font-family: inherit; font-size: 0.95rem; font-weight: 600; color: var(--text); cursor: pointer; }
  .save:hover { border-color: var(--accent); }

  .scoreband { display: flex; gap: 0.5rem; }
  .side { flex: 1; min-width: 0; text-align: center; padding: 0.8rem 0.5rem; border-radius: 14px; border: 1px solid var(--glass-border);
    background: linear-gradient(180deg, color-mix(in srgb, var(--tint) 38%, transparent), color-mix(in srgb, var(--tint) 10%, transparent)); }
  .side.winner { border-color: var(--tint); }
  .who { font-size: 1.15rem; font-weight: 700; padding-top: 0.5rem; overflow-wrap: anywhere; }
  .name-crown { position: relative; display: inline-block; }
  .legs { font-size: 2.6rem; font-weight: 800; line-height: 1.1; }

  .tabs, .legchips { display: flex; gap: 0.4rem; flex-wrap: wrap; }
  .tabs button, .legchips button { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 999px; padding: 0.4rem 1.1rem; font-family: inherit; font-size: 0.95rem; font-weight: 600; color: var(--muted); cursor: pointer; }
  .tabs button.on, .legchips button.on { color: var(--text); border-color: var(--accent); }

  .compare, .turns { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 14px; padding: 0.4rem 1rem; }
  .row, .trow { display: grid; grid-template-columns: minmax(5rem, 1.3fr) repeat(var(--cols), minmax(0, 1fr)); align-items: center; gap: 0.6rem; }
  .row { padding: 0.55rem 0; border-bottom: 1px solid var(--glass-border); }
  .row:last-child { border-bottom: none; }
  .row.head { font-weight: 700; font-size: 1rem; }
  .label { color: var(--muted); font-size: 0.95rem; }
  .cell { display: flex; flex-direction: column; gap: 0.3rem; font-size: 1.25rem; min-width: 0; }
  .cell b { font-weight: 700; }
  .cell b.best { color: var(--accent); }
  .bar { display: block; height: 0.3rem; border-radius: 999px; background: var(--glass-border); overflow: hidden; }
  .bar > i { display: block; height: 100%; border-radius: 999px; }

  .highlights { display: grid; grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr)); gap: 0.6rem; }
  .hl { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 14px; padding: 0.7rem 1rem; display: flex; flex-direction: column; gap: 0.1rem; }
  .hl-label, .hl-who { color: var(--muted); font-size: 0.85rem; }
  .hl b { font-size: 1.6rem; }

  .chart { width: 100%; height: auto; }
  .grid { stroke: var(--glass-border); stroke-width: 1; }
  .tick { fill: var(--muted); font-size: 10px; }

  .starts { margin-left: 0.5rem; padding: 0.05rem 0.5rem; border-radius: 999px; border: 1px solid currentColor; font-size: 0.7rem; font-weight: 600; vertical-align: middle; }
  .thead { padding: 0.5rem 0; font-weight: 700; border-bottom: 1px solid var(--glass-border); }
  .trow { padding: 0.4rem 0; }
  .trow:not(.thead) { border-bottom: 1px solid var(--glass-border); }
  .trow:last-child { border-bottom: none; }
  .trow > .n { color: var(--muted); font-size: 1rem; }
  .tcell { display: flex; flex-direction: column; min-width: 0; }
  .tcell b { font-size: 1.3rem; }
  .tcell em { font-style: normal; font-size: 1.05rem; color: color-mix(in srgb, var(--text) 78%, transparent); }
  .tcell.bust b { color: var(--red); }

  .heat { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 20rem), 1fr)); gap: 0.8rem; }
  .heat section { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 14px; padding: 0.8rem 1rem; }
  .hwho { font-size: 1.15rem; font-weight: 700; margin-bottom: 0.4rem; }
</style>
