<script>
  import { alertDialog } from '../../lib/confirm.js';
  import { openTv } from '../../lib/router.js';
  import { t } from '../../lib/i18n.js';
  // Warm-up setup: the stations to go over and one player. All is on until a station is picked, picking one switches
  // All off, and without any station picked All is on again. There is no limit of darts, a run ends when every field
  // has been hit or when it is finished.
  import { players } from '../../lib/stores/players.js';
  import NewPlayer from '../../lib/components/NewPlayer.svelte';
  import { shownName } from '../../lib/util.js';
  import Toggle from '../../lib/components/Toggle.svelte';
  import { KINDS, stationName, startRun } from '../../lib/warmUp.js';

  let player = $state(null);
  let all = $state(true);
  let picked = $state(Object.fromEntries(KINDS.map((kind) => [kind, false])));

  function pickAll() {
    all = true;
    for (const kind of KINDS) picked[kind] = false;
  }

  function pick(kind, on) {
    picked[kind] = on;
    all = !KINDS.some((k) => picked[k]);
  }

  async function start() {
    if (!player) { alertDialog(t('Select a player.')); return; }
    if (await startRun({ player, stations: all ? null : KINDS.filter((k) => picked[k]) })) openTv();
  }
</script>

<div class="section">
  <div class="section-title sub">{t('Stations')}</div>
  <Toggle bind:checked={all} label={t('All')} onchange={pickAll} />
  {#each KINDS as kind (kind)}
    <Toggle bind:checked={picked[kind]} label={stationName(kind)} onchange={(on) => pick(kind, on)} />
  {/each}
  <div class="hint">{t('The stations keep their order. The bull is thrown between two stations, the bull\'s eye comes last.')}</div>

  <div class="section-title sub">{t('Player')}</div>
  <div class="chips">
    {#each $players.known as name (name)}
      <button type="button" class="chip" class:in-game={player === name} onclick={() => (player = name)}>{shownName(name)}</button>
    {/each}
  </div>
  <NewPlayer onadded={(name) => (player = name)} />

  <button class="btn btn-start" onclick={start}>{t('▶ Start')}</button>
</div>

<style>
  .section { background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); border-radius: 16px; padding: 1.25rem; margin-bottom: 1rem; }
  .section-title { font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 1rem; }
  .section-title.sub { margin: 0 0 0.6rem; }
  .hint { color: var(--muted); font-size: 0.8rem; margin: 0.2rem 0 1.25rem; }
  .chips { display: flex; flex-wrap: wrap; gap: 0.4rem; max-height: 220px; overflow-y: auto; }
  .chip { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 20px; padding: 0.3rem 0.7rem; font-family: inherit; font-size: 0.85rem; cursor: pointer; transition: border-color 0.15s, color 0.15s; }
  .chip:hover { border-color: var(--accent); color: var(--accent); }
  .chip.in-game { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
  .btn { border: none; border-radius: 8px; padding: 0.65rem 1.5rem; font-size: 0.95rem; font-weight: 600; cursor: pointer; transition: opacity 0.15s; }
  .btn:hover { opacity: 0.85; }
  .btn-start { background: #166534; color: #fff; margin-top: 1.2rem; }
</style>
