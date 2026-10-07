import { api, apiJson } from './api.js';
import { t } from './i18n.js';

// The ranges of scores a run can be set to, by the score a finish starts from.
export const RANGES = [
  { id: 'low', low: 2, high: 40 },
  { id: 'mid', low: 41, high: 100 },
  { id: 'high', low: 101, high: 170 },
  { id: 'all', low: 2, high: 170 },
];

export function rangeLabel(low, high) {
  return low === 2 && high === 170 ? t('All scores') : `${low}–${high}`;
}

// A field as the board names it (S20, D16, T19, 25, 50, 0) for the screen.
export function fieldName(field) {
  if (field === '50') return t('Bull');
  if (field === '0') return t('Miss');
  return field;
}

export const routeText = (route) => (route || []).map(fieldName).join(' · ');

export const percent = (rate) => `${Math.round((rate || 0) * 100)} %`;

export async function startRun(setup) {
  const res = await apiJson('POST', '/api/checkout-training/start', setup);
  if (res.error) alert(t(res.error));
  return !res.error;
}

// The same run once more: same player, range, number of attempts and route setting.
export function rematch(co) {
  return startRun(co.setup);
}

// Clear the run so a new one can be set up. Whatever was finished stays saved.
export function stopRun() {
  return api('POST', '/api/checkout-training/stop');
}

// End the run early: the attempts so far are kept.
export function finishRun() {
  return api('POST', '/api/checkout-training/finish');
}

export function undoAttempt() {
  return api('POST', '/api/checkout-training/undo');
}

// The trainer without darts: the route quiz and the setup shots.
export async function randomScore(low, high, avoid) {
  const query = `low=${low}&high=${high}` + (avoid ? `&avoid=${avoid}` : '');
  const res = await fetch(`/api/checkout/random?${query}`).then((r) => r.json());
  return res.score ?? null;
}

export function judgeFirstDart(score, field) {
  return apiJson('POST', '/api/checkout/judge', { score, field });
}

export function setupResult(score, fields) {
  return apiJson('POST', '/api/checkout/setup', { score, fields });
}
