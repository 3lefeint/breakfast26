import { writable } from 'svelte/store';

// How the aurora behaves (`[web] aurora_animation`, `aurora_streaks`, `aurora_pause_idle`). Settings sets
// them when the choice is saved or previewed, so the page changes at once.
export const auroraAnimated = writable(true);
export const auroraStreaks = writable(true);
export const auroraPauseIdle = writable(0);

const HEX = /^#[0-9a-fA-F]{6}$/;
const AURORA_VARS = { base: '--aurora-base', 1: '--aurora-1', 2: '--aurora-2', 3: '--aurora-3' };

// The colors of the aurora: a color from the settings replaces the one of the palette or theme, nothing set
// leaves it. Also used by Settings to preview a color while it is picked.
export function applyAuroraColors(colors = {}) {
  const root = document.documentElement.style;
  for (const [key, cssVar] of Object.entries(AURORA_VARS)) {
    const value = colors[key];
    if (value && HEX.test(value)) root.setProperty(cssVar, value);
    else root.removeProperty(cssVar);
  }
}

// The look besides the colors: a ready-made palette, how fast, strong and soft the aurora is, and how
// milky the glass panels are. Percent values become the factors the CSS multiplies with.
const FACTORS = { speed: '--aurora-speed', intensity: '--aurora-intensity', blur: '--aurora-blur', glass: '--glass-a' };
export function applyLook(look = {}) {
  const root = document.documentElement;
  if (look.palette) root.dataset.aurora = look.palette;
  else delete root.dataset.aurora;
  for (const [key, cssVar] of Object.entries(FACTORS)) {
    if (Number.isFinite(look[key])) root.style.setProperty(cssVar, String(look[key] / 100));
    else root.style.removeProperty(cssVar);
  }
  if (Number.isFinite(look.bar)) root.style.setProperty('--bar-a', look.bar + '%');
  else root.style.removeProperty('--bar-a');
  auroraStreaks.set(look.streaks !== false);
  auroraPauseIdle.set(Number.isFinite(look.pause_idle) ? look.pause_idle : 0);
}

// What the installation looks like (`[web]`): theme, accent color, aurora, glass. Every page applies it at start.
export function applyAppearance(a) {
  const root = document.documentElement;
  if (a.theme) root.dataset.theme = a.theme;
  else delete root.dataset.theme;
  if (a.accent_color) root.style.setProperty('--accent', a.accent_color);
  else root.style.removeProperty('--accent');
  applyAuroraColors(a.aurora);
  applyLook(a);
  auroraAnimated.set(a.aurora_animation !== false);
}

export async function loadAppearance() {
  try {
    applyAppearance(await fetch('/api/appearance').then((r) => r.json()));
  } catch (_) {
    // no answer: the theme and the moving aurora stay as they are
  }
}
