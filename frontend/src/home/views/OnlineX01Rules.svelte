<script>
  import { t } from '../../lib/i18n.js';
  // The rules of an online X01 match in the lobby: the host sets them, the other sites see them as they are (they come
  // back from the relay with the lobby). The order of the players is the lobby's business.
  import Toggle from '../../lib/components/Toggle.svelte';
  import { START_SCORES, MODES, MAX_LEGS, MAX_ROUNDS_CHOICES, inLabel, outLabel, ruleChips } from '../../lib/x01.js';

  let { rules = $bindable(), editable = true, onbulloff = () => {} } = $props();

  const MODE_LABEL = { straight: () => t('Straight'), double: () => t('Double'), master: () => t('Master') };
  function setScore(e) {
    const n = parseInt(e.target.value, 10);
    if (Number.isFinite(n)) rules.start = Math.max(2, Math.min(1501, n));
  }
</script>

{#if editable}
  <div class="rules">
    <div class="option-row">
      <span class="label">{t('Base Score')}</span>
      <div class="seg">
        {#each START_SCORES as s (s)}
          <button type="button" class="seg-btn" class:active={rules.start === s} onclick={() => (rules.start = s)}>{s}</button>
        {/each}
        <input class="score-input" type="number" min="2" max="1501" value={rules.start} onchange={setScore}>
      </div>
    </div>
    <div class="option-row">
      <span class="label">{t('In Mode')}</span>
      <div class="seg">
        {#each MODES as m (m)}
          <button type="button" class="seg-btn" class:active={rules.in_mode === m} onclick={() => (rules.in_mode = m)}>{MODE_LABEL[m]()}</button>
        {/each}
      </div>
    </div>
    <div class="option-row">
      <span class="label">{t('Out Mode')}</span>
      <div class="seg">
        {#each MODES as m (m)}
          <button type="button" class="seg-btn" class:active={rules.out_mode === m} onclick={() => (rules.out_mode = m)}>{MODE_LABEL[m]()}</button>
        {/each}
      </div>
    </div>
    <div class="option-row">
      <span class="label">{t('Max Rounds')}</span>
      <div class="seg">
        {#each MAX_ROUNDS_CHOICES as n (n)}
          <button type="button" class="seg-btn" class:active={rules.max_rounds === n} onclick={() => (rules.max_rounds = n)}>{n ?? t('No limit')}</button>
        {/each}
      </div>
    </div>
    <div class="option-row">
      <span class="label">{t('Legs to win')}</span>
      <div class="counter">
        <button type="button" class="btn-counter" onclick={() => (rules.legs = Math.max(1, rules.legs - 1))}>−</button>
        <span class="counter-val">{rules.legs}</span>
        <button type="button" class="btn-counter" onclick={() => (rules.legs = Math.min(MAX_LEGS, rules.legs + 1))}>+</button>
      </div>
    </div>
    <Toggle bind:checked={rules.bull_off} label={t('Bull-Off')} onchange={(v) => onbulloff(v)} />
  </div>
{:else}
  <p class="summary">
    <strong>{rules.start}</strong>
    {#each ruleChips({ rules }) as chip (chip)}<span class="chip">{chip}</span>{/each}
    {#if rules.bull_off}<span class="chip">{t('Bull-Off')}</span>{/if}
  </p>
{/if}

<style>
  .option-row { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.8rem; flex-wrap: wrap; }
  .option-row .label { font-size: 0.9rem; color: var(--muted); min-width: 8rem; }
  .seg { display: flex; gap: 0.4rem; flex-wrap: wrap; align-items: center; }
  .seg-btn { background: var(--glass); border: 1px solid var(--glass-border); color: var(--muted); border-radius: 20px; padding: 0.3rem 0.9rem; font-family: inherit; font-size: 0.85rem; cursor: pointer; }
  .seg-btn:hover { border-color: var(--accent); color: var(--text); }
  .seg-btn.active { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); font-weight: 700; }
  .score-input { width: 5rem; background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); color: var(--text); border-radius: 12px; padding: 0.3rem 0.6rem; font-size: 0.85rem; font-family: inherit; }
  .counter { display: flex; align-items: center; gap: 0.5rem; }
  .counter-val { font-size: 1.15rem; font-weight: 700; min-width: 1.4rem; text-align: center; }
  .btn-counter { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 8px; width: 1.5rem; height: 1.5rem; cursor: pointer; font-size: 0.95rem; line-height: 1; display: flex; align-items: center; justify-content: center; }
  .btn-counter:hover { border-color: var(--accent); }
  .summary { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; margin: 0.25rem 0 0.75rem; font-size: 1.1rem; }
  .chip { font-size: 0.8rem; color: var(--muted); border: 1px solid var(--glass-border); border-radius: 20px; padding: 0.15rem 0.7rem; }
  @media (max-width: 640px) { .option-row .label { min-width: 0; width: 100%; } }
</style>
