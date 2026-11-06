<script>
  import { t } from '../../lib/i18n.js';
  // The fields of one effect: type, color, speed and thickness of the frame. `effect` is null for no effect;
  // `onchange` gets the new effect (or null) after every edit.
  let { effect, effects, onchange, allowNone = true } = $props();

  const LABEL = { pulse: t('Pulse'), blink: t('Blink'), chase: t('Chase') };
  const fresh = (type) => ({ type, color: '#ff0000', speed: 1, width: 6 });
  const choose = (e) => {
    const type = e.currentTarget.value;
    onchange(type ? { ...(effect || fresh(type)), type } : null);
  };
  const set = (key, number) => (e) => onchange({ ...effect, [key]: number ? Number(e.currentTarget.value) : e.currentTarget.value });
</script>

<label class="field">
  <span>{t('Effect')}</span>
  <select value={effect?.type || ''} onchange={choose}>
    {#if allowNone}<option value="">{t('None')}</option>{/if}
    {#each effects as type (type)}<option value={type}>{LABEL[type]}</option>{/each}
  </select>
</label>
{#if effect}
  <div class="field">
    <span>{t('Color')}</span>
    <input type="color" value={effect.color} onchange={set('color', false)} aria-label={t('Color')}>
  </div>
  <label class="field">
    <span>{t('Speed')}</span>
    <input type="range" min="0.1" max="5" step="0.1" value={effect.speed} onchange={set('speed', true)}>
    <span class="val">{effect.speed} / s</span>
  </label>
  <label class="field">
    <span>{t('Frame thickness')}</span>
    <input type="range" min="1" max="24" value={effect.width} onchange={set('width', true)}>
    <span class="val">{effect.width}</span>
  </label>
{/if}

<style>
  .field { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.6rem; font-size: 0.9rem; color: var(--muted); flex-wrap: wrap; }
  .field > span:first-child { min-width: 5rem; }
  .field select { flex: 1; min-width: 8rem; background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 6px; color: var(--text); padding: 0.35rem 0.55rem; font-family: inherit; font-size: 0.85rem; }
  .field input[type="range"] { flex: 0 1 12rem; accent-color: var(--accent); }
  input[type="color"] { width: 2.6rem; height: 1.8rem; padding: 0; border: 1px solid var(--glass-border); border-radius: 6px; background: none; }
  .val { font-size: 0.8rem; min-width: 3rem; }
</style>
