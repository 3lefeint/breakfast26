<script>
  import { t } from '../../lib/i18n.js';
  // The tracker settings of the own dart detection that can be changed while it runs (see breakfast/detection/tuning.py for the
  // ranges). A change is kept by the detection and wins over config.toml; "Back to config.toml" removes it.
  import { onMount } from 'svelte';
  import { apiJson } from '../../lib/api.js';
  import Toggle from '../../lib/components/Toggle.svelte';

  let items = $state([]);
  let values = $state({});
  let refused = $state({});
  let saved = $state(false);

  const TEXTS = {
    settle_s: [() => t('Settle time (s)'), () => t('How long the board must be still before it is checked. Shorter calls the dart sooner, longer waits for a wobbling dart.')],
    motion_fraction: [() => t('Movement threshold'), () => t('Share of the camera image that must change to count as movement. Higher ignores small changes (light, vibration).')],
    uncertain_margin_mm: [() => t('Uncertain near a wire (mm)'), () => t('A dart closer than this to a wire or ring is marked as uncertain.')],
    uncertain_sigma: [() => t('Uncertain when the position is vague (mm)'), () => t('A dart whose position the cameras only know to within this is marked as uncertain.')],
    recount: [() => t('Recover missed darts'), () => t('Counts a dart that the camera image shows but the count missed.')],
    recount_looks: [() => t('Checks before a missed dart is counted'), () => t('How many settled checks in a row must show the dart at the same place.')],
    exposure: [() => t('Camera exposure'), () => t('Fixes the exposure time of all cameras (units of 0.1 ms, larger is brighter). 0 leaves it to the camera, which follows an arm in the camera image and then looks like a change of the board. Aim for a brightness of about 120.')],
    white_balance: [() => t('Camera white balance (K)'), () => t('Fixes the color temperature of all cameras. 0 leaves it to the camera.')],
  };
  const AUTOMATIC = ['exposure', 'white_balance'];   // 0 means the camera's automatic besides the range
  let brightness = $state([]);

  function take(list) {
    items = list;
    values = Object.fromEntries(list.map((i) => [i.key, i.value]));
    refused = {};
  }
  async function load() {
    const res = await apiJson('GET', '/api/detection/settings');
    if (res.settings) take(res.settings);
  }
  async function look() {
    const res = await apiJson('GET', '/api/detection/status');
    brightness = (res.cameras ?? []).map((c) => c.brightness);
  }
  onMount(() => {
    load();
    look();
    const timer = setInterval(look, 3000);
    return () => clearInterval(timer);
  });

  const changed = $derived(items.filter((i) => values[i.key] !== i.value));

  async function save() {
    const res = await apiJson('POST', '/api/detection/settings', Object.fromEntries(changed.map((i) => [i.key, values[i.key]])));
    if (res.error) return alert(t(res.error));
    await load();
    refused = res.refused ?? {};
    saved = Object.keys(refused).length === 0;
    setTimeout(() => (saved = false), 2500);
  }
  async function reset() {
    if (!confirm(t('Restore the default values?'))) return;
    const res = await apiJson('POST', '/api/detection/settings/reset', {});
    if (res.settings) take(res.settings);
  }
</script>

<div class="settings">
  {#each items as i (i.key)}
    <div class="row">
      {#if i.kind === 'bool'}
        <Toggle bind:checked={values[i.key]} label={TEXTS[i.key][0]()} wide />
      {:else}
        <label class="field">
          <span class="label">{TEXTS[i.key][0]()}</span>
          <input type="number" min={i.min} max={i.max} step={i.kind === 'int' ? 1 : 'any'} bind:value={values[i.key]}>
          <span class="range">{AUTOMATIC.includes(i.key) ? `0 = ${t('Automatic')}, ` : ''}{i.min} – {i.max} ({t('Default')} {i.default})</span>
        </label>
      {/if}
      <div class="hint">{TEXTS[i.key][1]()}</div>
      {#if i.key === 'exposure' && brightness.length}<div class="hint">{t('Brightness of the camera images')}: {brightness.map((b) => b ?? '–').join(' / ')}</div>{/if}
      {#if refused[i.key]}<div class="err">{refused[i.key]}</div>{/if}
    </div>
  {/each}
  <div class="buttons">
    <button class="btn" disabled={!changed.length} onclick={save}>{t('Save')}</button>
    <button class="btn" onclick={reset}>{t('Restore defaults')}</button>
    {#if saved}<span class="ok">{t('Saved')}</span>{/if}
  </div>
</div>

<style>
  .settings { display: flex; flex-direction: column; gap: 0.2rem; }
  .row { margin-bottom: 0.6rem; }
  .field { display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap; }
  .label { font-size: 0.9rem; color: var(--muted); min-width: 16rem; }
  input[type='number'] { width: 7rem; background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 8px; padding: 0.3rem 0.5rem; font: inherit; }
  .range { font-size: 0.75rem; color: var(--muted); }
  .hint { font-size: 0.78rem; color: var(--muted); margin-top: 0.15rem; }
  .err { font-size: 0.8rem; color: var(--red); }
  .buttons { display: flex; gap: 0.6rem; align-items: center; margin-top: 0.5rem; }
  .btn { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 10px; padding: 0.45rem 1rem; font: inherit; cursor: pointer; }
  .btn:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
  .btn:disabled { opacity: 0.5; cursor: default; }
  .ok { color: var(--green); font-size: 0.85rem; }
</style>
