import { api, apiJson } from './api.js';
import { t } from './i18n.js';

export const BULL = 25;

export function fieldLabel(field) {
  return field === BULL ? t('Bull') : String(field);
}

// The number of darts a run has by default, and from which on it counts for the personal best and the rating.
export function standardDarts(field) {
  return field === BULL ? 50 : 100;
}

export const RATING_LABELS = { beginner: t('Beginner'), advanced: t('Advanced'), pro: t('Pro') };

export async function startRun(setup) {
  const res = await apiJson('POST', '/api/field-training/start', setup);
  if (res.error) alert(t(res.error));
  return !res.error;
}

// Throw the same run once more: same player, field and number of darts.
export function rematch(ft) {
  return startRun(ft.setup);
}

// Clear the run so a new one can be set up. Whatever was thrown stays saved.
export function stopRun() {
  return api('POST', '/api/field-training/stop');
}

// End the run early: the darts thrown so far are kept as practice.
export function finishRun() {
  return api('POST', '/api/field-training/finish');
}

export function undoTurn() {
  return api('POST', '/api/field-training/undo');
}

export const percent = (rate) => `${Math.round((rate || 0) * 100)} %`;

// Every dart of the run as a small dot for the board: the color says what it scored.
export function runDots(ft) {
  return (ft.all_darts || []).map((d, i) => ({ n: `d${i}`, x: d.x, y: d.y, dot: true, scored: d.points }));
}
