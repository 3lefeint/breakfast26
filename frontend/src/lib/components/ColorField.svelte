<script>
  import { t } from '../i18n.js';
  // A color as a swatch, a hex field and, when the swatch is clicked, three sliders (hue, saturation,
  // brightness) with the color range drawn on each track. The browser's own color dialog hides the
  // brightness, which is what matters for the dark colors of the aurora. `value` is a hex color or ''
  // (not set: `fallback` is shown); every change calls `onchange` with the new hex string.
  let { value = '', fallback = '#000000', id = undefined, label = '', onchange = () => {} } = $props();

  const HEX = /^#[0-9a-fA-F]{6}$/;

  function hexToHsl(hex) {
    const r = parseInt(hex.slice(1, 3), 16) / 255;
    const g = parseInt(hex.slice(3, 5), 16) / 255;
    const b = parseInt(hex.slice(5, 7), 16) / 255;
    const max = Math.max(r, g, b);
    const min = Math.min(r, g, b);
    const l = (max + min) / 2;
    const d = max - min;
    if (d === 0) return [0, 0, Math.round(l * 100)];
    const s = d / (1 - Math.abs(2 * l - 1));
    let h;
    if (max === r) h = ((g - b) / d) % 6;
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    return [Math.round((h * 60 + 360) % 360), Math.round(s * 100), Math.round(l * 100)];
  }

  function hslToHex(h, s, l) {
    s /= 100;
    l /= 100;
    const k = (n) => (n + h / 30) % 12;
    const a = s * Math.min(l, 1 - l);
    const f = (n) => Math.round(255 * (l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)))));
    return '#' + [f(0), f(8), f(4)].map((x) => x.toString(16).padStart(2, '0')).join('');
  }

  let open = $state(false);
  let shown = $derived(HEX.test(value) ? value : fallback);
  let hue = $state(0);
  let sat = $state(0);
  let light = $state(0);
  let emitted = null;

  // Take the sliders from the color whenever it was changed from outside (typing a hex value, a reset).
  $effect(() => {
    if (shown !== emitted && HEX.test(shown)) [hue, sat, light] = hexToHsl(shown);
  });

  function slide() {
    emitted = hslToHex(hue, sat, light);
    onchange(emitted);
  }
</script>

<div class="color-field">
  <button type="button" class="swatch" style:background={shown} aria-label={label} aria-expanded={open}
          onclick={() => (open = !open)}></button>
  <input type="text" class="hex" {id} placeholder={t('from the theme')} maxlength="7" {value}
         oninput={(e) => onchange(e.currentTarget.value)}>
  {#if open}
    <div class="sliders">
      <label><span>{t('Hue')}</span>
        <input type="range" min="0" max="360" bind:value={hue} oninput={slide}
               style:background="linear-gradient(90deg, hsl(0 {Math.max(sat, 40)}% 50%), hsl(60 {Math.max(sat, 40)}% 50%), hsl(120 {Math.max(sat, 40)}% 50%), hsl(180 {Math.max(sat, 40)}% 50%), hsl(240 {Math.max(sat, 40)}% 50%), hsl(300 {Math.max(sat, 40)}% 50%), hsl(360 {Math.max(sat, 40)}% 50%))"></label>
      <label><span>{t('Saturation')}</span>
        <input type="range" min="0" max="100" bind:value={sat} oninput={slide}
               style:background="linear-gradient(90deg, hsl({hue} 0% {light}%), hsl({hue} 100% {light}%))"></label>
      <label><span>{t('Brightness')}</span>
        <input type="range" min="0" max="100" bind:value={light} oninput={slide}
               style:background="linear-gradient(90deg, #000, hsl({hue} {sat}% 50%), #fff)"></label>
    </div>
  {/if}
</div>

<style>
  .color-field { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; flex: 1; min-width: 0; }
  .swatch {
    width: 2.6rem; height: 2.2rem; flex: none; padding: 0; cursor: pointer;
    border: 1px solid var(--glass-border); border-radius: 8px;
  }
  .swatch[aria-expanded="true"] { border-color: var(--accent); }
  .hex {
    flex: 1; min-width: 0; background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border);
    border-radius: 10px; color: var(--text); padding: 0.45rem 0.75rem; font-size: 0.9rem; font-family: inherit;
  }
  .hex:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 25%, transparent); }
  .sliders { flex-basis: 100%; display: flex; flex-direction: column; gap: 0.45rem; padding: 0.2rem 0 0.3rem; }
  .sliders label { display: flex; align-items: center; gap: 0.7rem; font-size: 0.8rem; color: var(--muted); }
  .sliders span { width: 5.5rem; flex: none; }
  input[type="range"] {
    flex: 1; min-width: 0; height: 0.8rem; border-radius: 999px; padding: 0; appearance: none; -webkit-appearance: none;
    border: 1px solid var(--glass-border); cursor: pointer;
  }
  input[type="range"]::-webkit-slider-thumb {
    -webkit-appearance: none; width: 1.1rem; height: 1.1rem; border-radius: 50%; background: #fff; border: 2px solid #222; cursor: pointer;
  }
  input[type="range"]::-moz-range-thumb { width: 1.1rem; height: 1.1rem; border-radius: 50%; background: #fff; border: 2px solid #222; cursor: pointer; }
</style>
