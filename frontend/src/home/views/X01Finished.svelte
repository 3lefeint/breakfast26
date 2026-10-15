<script>
  import { openTv } from '../../lib/router.js';
  import { t } from '../../lib/i18n.js';
  // The result of a finished X01 match on Home: the legs won, the average, a rematch with the same
  // players and rules, a new setup, correcting a dart of the last turn or undoing it. A match won by
  // mistake resumes after a correction or an undo.
  import { x01Own } from '../../lib/stores/x01Own.js';
  import { gameState } from '../../lib/stores/gameState.js';
  import { api } from '../../lib/api.js';
  import { cap } from '../../lib/util.js';
  import { dartLabel } from '../../lib/killer.js';
  import { rematch, stopGame, ruleChips } from '../../lib/x01.js';
  import ConfettiBurst from '../../lib/components/ConfettiBurst.svelte';
  import DartCorrectModal from '../../tv/views/DartCorrectModal.svelte';

  let x = $derived($x01Own);
  let stats = $derived($gameState.session_stats || {});
  let rows = $derived([...(x?.players || [])].sort((a, b) => b.legs_won - a.legs_won));
  let lastDarts = $derived(x?.last_turn?.darts || []);
  let correctingIndex = $state(null);

  async function again() {
    if (await rematch(x)) openTv();
  }

  async function undoWin() {
    if (!confirm(t('Undo the last turn and resume the game?'))) return;
    await api('POST', '/api/x01/undo');
  }
</script>

{#if x}
  <ConfettiBurst />
  <div class="section finished">
    <div class="heading">{t('{name} wins', { name: cap(x.winner || '') })}</div>
    <div class="meta">{[x.rules.start, ...ruleChips(x)].join(' · ')}</div>
    <ul class="results">
      {#each rows as p (p.name)}
        <li class:winner={p.name === x.winner}>
          <span class="who">{cap(p.name)}</span>
          <span class="avg">{stats[p.name]?.avg3 != null ? `${t('Avg')} ${stats[p.name].avg3.toFixed(1)}` : ''}</span>
          <span class="legs">{p.legs_won} {t('Legs')}</span>
        </li>
      {/each}
    </ul>
    {#if lastDarts.length}
      <div class="last">
        <span class="last-label">{t('Last turn, {name}', { name: cap(x.last_turn.player) })}</span>
        {#each lastDarts as d, i}
          <button type="button" class="dart-chip" onclick={() => (correctingIndex = i)}>{dartLabel(d)}</button>
        {/each}
        <span class="hint">{t('tap a dart to correct it')}</span>
      </div>
    {/if}
    <div class="actions">
      <button class="btn btn-start" onclick={again}>{t('↻ Rematch')}</button>
      <button class="btn ghost" onclick={stopGame}>{t('New game')}</button>
      <button class="btn ghost" onclick={undoWin}>{t('↩ Undo last turn')}</button>
    </div>
  </div>
{/if}

{#if correctingIndex != null}
  <DartCorrectModal dartIndex={correctingIndex} onClose={() => (correctingIndex = null)}
                    endpoint="/api/x01/correct-last-dart" />
{/if}

<style>
  .section { background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); border-radius: 16px; padding: 1.5rem; margin-bottom: 1rem; }
  .heading { font-size: 1.6rem; font-weight: 800; color: var(--green); }
  .meta { color: var(--muted); font-size: 0.85rem; margin: 0.25rem 0 1rem; }
  .results { list-style: none; padding: 0; margin-bottom: 1.25rem; }
  .results li { display: grid; grid-template-columns: 1fr auto auto; gap: 1rem; align-items: center; padding: 0.55rem 0.8rem; margin-top: 0.5rem; border: 1px solid var(--glass-border); border-radius: 12px; background: rgba(0, 0, 0, 0.22); }
  .results li.winner { border-color: color-mix(in srgb, var(--green) 55%, transparent); }
  .avg { color: var(--muted); font-size: 0.85rem; }
  .legs { font-weight: 700; }
  .last { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 1.25rem; }
  .last-label { color: var(--muted); font-size: 0.85rem; }
  .hint { color: var(--muted); font-size: 0.75rem; }
  .dart-chip { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 10px; padding: 0.3rem 0.8rem; font-family: inherit; font-weight: 700; color: var(--text); cursor: pointer; }
  .dart-chip:hover { border-color: var(--accent); }
  .actions { display: flex; gap: 0.6rem; flex-wrap: wrap; }
  .btn { border: none; border-radius: 8px; padding: 0.65rem 1.4rem; font-size: 0.95rem; font-weight: 600; cursor: pointer; }
  .btn-start { background: #166534; color: #fff; }
  .btn.ghost { background: var(--glass); color: color-mix(in srgb, var(--text) 82%, transparent); border: 1px solid var(--glass-border); }
  .btn.ghost:hover { border-color: var(--accent); color: var(--text); }
</style>
