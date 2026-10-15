<script>
  import { navigate } from '../../lib/router.js';
  import { t } from '../../lib/i18n.js';
  // The result of a finished X01 match on the TV: the winner marked with the crown, the legs won and
  // the average of each player, and the darts of the last turn. A dart tapped here is corrected and
  // the match resumes when that turn did not decide it after all.
  import { cap } from '../../lib/util.js';
  import { api } from '../../lib/api.js';
  import { dartLabel } from '../../lib/killer.js';
  import { rematch, stopGame, ruleChips } from '../../lib/x01.js';
  import Crown from '../../lib/components/Crown.svelte';
  import ConfettiBurst from '../../lib/components/ConfettiBurst.svelte';
  import DartCorrectModal from './DartCorrectModal.svelte';

  let { x, sessionStats = {} } = $props();

  let rows = $derived([...(x.players || [])].sort((a, b) => b.legs_won - a.legs_won));
  let lastDarts = $derived(x.last_turn?.darts || []);
  let correctingIndex = $state(null);

  async function undo() {
    if (!confirm(t('Undo the last turn and resume the game?'))) return;
    await api('POST', '/api/x01/undo');
  }

  async function done() {
    await stopGame();
    navigate('x01');
  }
</script>

<ConfettiBurst />

<div class="finished">
  <div class="heading">{t('{name} wins', { name: cap(x.winner || '') })}</div>
  <div class="meta">{[x.rules.start, ...ruleChips(x)].join(' · ')}</div>
  <ul class="results">
    {#each rows as p (p.name)}
      <li class:winner={p.name === x.winner}>
        <span class="name-crown">{#if p.name === x.winner}<Crown />{/if}{cap(p.name)}</span>
        <span class="avg">{sessionStats[p.name]?.avg3 != null ? `${t('Avg')} ${sessionStats[p.name].avg3.toFixed(1)}` : ''}</span>
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
    </div>
  {/if}
  <div class="actions">
    <button class="btn" onclick={() => rematch(x)}>{t('↻ Rematch')}</button>
    <button class="btn ghost" onclick={undo}>{t('↩ Undo last turn')}</button>
    <button class="btn ghost" onclick={done}>{t('Done')}</button>
  </div>
</div>

{#if correctingIndex != null}
  <DartCorrectModal dartIndex={correctingIndex} onClose={() => (correctingIndex = null)}
                    endpoint="/api/x01/correct-last-dart" />
{/if}

<style>
  .finished { flex: 1; min-height: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 1.4rem; padding: 1.5rem 2rem; }
  .heading { font-size: clamp(2rem, 5vw, 4.2rem); font-weight: 800; color: var(--green); text-align: center; }
  .meta { color: var(--muted); font-size: clamp(0.8rem, 1.3vw, 1.2rem); margin-top: -1rem; }
  .results { list-style: none; padding: 0; width: min(36rem, 90vw); max-height: 42vh; overflow-y: auto; }
  .results li {
    display: grid; grid-template-columns: 1fr auto auto; align-items: center; gap: 1.2rem;
    padding: 0.6rem 1.2rem; margin-top: 0.6rem; border-radius: 16px;
    background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); font-size: clamp(1.1rem, 2.2vw, 1.9rem);
  }
  .results li.winner { border-color: color-mix(in srgb, var(--green) 55%, transparent); }
  .name-crown { position: relative; display: inline-block; }
  .avg { color: var(--muted); font-size: 0.7em; }
  .legs { font-weight: 800; }
  .last { display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap; justify-content: center; }
  .last-label { color: var(--muted); font-size: clamp(0.85rem, 1.4vw, 1.3rem); }
  .dart-chip { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 10px; padding: 0.4rem 1rem; font-family: inherit; font-size: clamp(1rem, 1.8vw, 1.6rem); font-weight: 700; color: var(--text); cursor: pointer; }
  .dart-chip:hover { border-color: var(--accent); }
  .actions { display: flex; gap: 0.8rem; flex-wrap: wrap; justify-content: center; }
  .btn { background: #166534; color: #fff; border: none; border-radius: 999px; padding: 0.7rem 1.6rem; font-size: 1rem; font-weight: 600; cursor: pointer; }
  .btn.ghost { background: var(--glass); color: color-mix(in srgb, var(--text) 82%, transparent); border: 1px solid var(--glass-border); }
  .btn.ghost:hover { border-color: var(--accent); color: var(--text); }
</style>
