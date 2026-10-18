<script>
  import { confirmDialog } from '../../lib/confirm.js';
  import { navigate } from '../../lib/router.js';
  import { t } from '../../lib/i18n.js';
  // The result of a finished X01 match on the TV: the winner marked with the crown, the legs won and
  // the average of each player, and the darts of the last turn. A dart tapped here is corrected and
  // the match resumes when that turn did not decide it after all.
  import { cap } from '../../lib/util.js';
  import { api } from '../../lib/api.js';
  import { dartLabel } from '../../lib/killer.js';
  import { rematch, stopGame, ruleChips } from '../../lib/x01.js';
  import Avatar from '../../lib/components/Avatar.svelte';
  import { gameState } from '../../lib/stores/gameState.js';
  import Crown from '../../lib/components/Crown.svelte';
  import ConfettiBurst from '../../lib/components/ConfettiBurst.svelte';
  import DartCorrectModal from './DartCorrectModal.svelte';
  import X01Summary from '../../lib/components/X01Summary.svelte';

  let { x, sessionStats = {} } = $props();

  let rows = $derived([...(x.players || [])].sort((a, b) => b.legs_won - a.legs_won));
  // Players with the same number of legs share a place.
  let place = (p) => 1 + rows.filter((o) => o.legs_won > p.legs_won).length;
  let lastDarts = $derived(x.last_turn?.darts || []);
  let correctingIndex = $state(null);
  let showSummary = $state(false);

  // The summary is as high as the window, so the footer stays at the bottom and the summary scrolls inside.
  $effect(() => {
    document.body.classList.toggle('tv-fixed-height', showSummary);
    return () => document.body.classList.remove('tv-fixed-height');
  });

  async function undo() {
    if (!await confirmDialog(t('Undo the last turn and resume the game?'))) return;
    await api('POST', '/api/x01/undo');
  }

  async function done() {
    await stopGame();
    navigate('x01');
  }
</script>

{#if showSummary}
  <div class="summary-page">
    <X01Summary matchId={x.match_id} />
    <div class="actions">
      <button class="btn ghost" onclick={() => (showSummary = false)}>{t('← Result')}</button>
    </div>
  </div>
{:else}
<ConfettiBurst />

<div class="finished">
  <div class="heading">{t('{name} wins', { name: cap(x.winner || '') })}</div>
  <div class="meta">{[x.rules.start, ...ruleChips(x)].join(' · ')}</div>
  <ul class="results">
    {#each rows as p (p.name)}
      <li class:winner={p.name === x.winner}>
        <span class="place">{place(p)}</span>
        <span class="who">
          <span class="swatch"><Avatar name={p.name || ''} color={$gameState.player_colors?.[p.name] || null} size={100} /></span>
          <span class="name-crown">{#if p.name === x.winner}<Crown />{/if}{cap(p.name)}</span>
        </span>
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
    <button class="btn ghost" onclick={() => (showSummary = true)}>{t('Summary')}</button>
    <button class="btn ghost" onclick={undo}>{t('↩ Undo')}</button>
    <button class="btn ghost" onclick={done}>{t('✓ Done')}</button>
  </div>
</div>

{#if correctingIndex != null}
  <DartCorrectModal dartIndex={correctingIndex} onClose={() => (correctingIndex = null)}
                    endpoint="/api/x01/correct-last-dart" />
{/if}
{/if}

<style>
  :global(body.tv-fixed-height #app) { height: 100dvh; }
  .summary-page { flex: 1 1 0; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 1rem; padding: 1.5rem 2rem; }
  .finished { flex: 1; min-height: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 1.4rem; padding: 1.5rem 2rem; }
  .heading { font-size: clamp(2rem, 5vw, 4.2rem); font-weight: 800; color: var(--green); text-align: center; }
  .meta { color: var(--muted); font-size: clamp(0.8rem, 1.3vw, 1.2rem); margin-top: -1rem; }
  .results { list-style: none; padding: 0; width: min(36rem, 90vw); max-height: 42vh; overflow-y: auto; }
  .results li {
    display: grid; grid-template-columns: 2.5rem 1fr auto auto; align-items: center; gap: 1rem;
    padding: 0.6rem 1.2rem; margin-top: 0.6rem; border-radius: 16px;
    background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); font-size: clamp(1.1rem, 2.2vw, 1.9rem);
  }
  .results li.winner { border-color: color-mix(in srgb, var(--green) 55%, transparent); }
  .place { color: var(--muted); font-weight: 700; }
  .who { display: flex; align-items: center; gap: 0.7em; }
  .name-crown { position: relative; display: inline-block; }
  .swatch { width: 1.5em; height: 1.5em; border-radius: 50%; flex-shrink: 0; align-self: center; overflow: visible; }
  .swatch :global(svg) { width: 100%; height: 100%; }
  .avg { color: var(--muted); font-size: 0.7em; }
  .legs { font-weight: 800; }
  .last { display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap; justify-content: center; }
  .last-label { color: var(--muted); font-size: clamp(0.85rem, 1.4vw, 1.3rem); }
  .dart-chip { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 10px; padding: 0.4rem 1rem; font-family: inherit; font-size: clamp(1rem, 1.8vw, 1.6rem); font-weight: 700; color: var(--text); cursor: pointer; }
  .dart-chip:hover { border-color: var(--accent); }
  .actions { display: flex; gap: 1vw; flex-wrap: wrap; justify-content: center; }
  .btn { background: #166534; color: #fff; border: none; border-radius: 999px; padding: 0.75rem 2rem; font-size: clamp(1rem, 1.5vw, 1.6rem); font-weight: 600; cursor: pointer; transition: border-color 0.15s, color 0.15s, background 0.15s; }
  .btn:hover { background: #15803d; }
  .btn.ghost { background: var(--glass); color: color-mix(in srgb, var(--text) 82%, transparent); border: 1px solid var(--glass-border); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2); }
  .btn.ghost:hover { background: var(--glass); border-color: var(--accent); color: var(--text); }
</style>
