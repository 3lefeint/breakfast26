import { api, apiJson } from './api.js';
import { t } from './i18n.js';

// A field of the ladder: D5, or the bull's eye (25) which is always last.
export function stepLabel(field) {
  return field === 25 ? t('Bull') : `D${field}`;
}

export async function startRun(setup) {
  const res = await apiJson('POST', '/api/black-belt/start', setup);
  if (res.error) alert(t(res.error));
  return !res.error;
}

// Another run with the same player and direction.
export function rematch(bb) {
  return startRun(bb.setup);
}

// Clear the run so a new one can be set up. Whatever was thrown stays saved.
export function stopRun() {
  return api('POST', '/api/black-belt/stop');
}

// End the run: the darts thrown so far are kept.
export function finishRun() {
  return api('POST', '/api/black-belt/finish');
}

export function undoTurn() {
  return api('POST', '/api/black-belt/undo');
}

// Every dart of the run as a small dot for the board: the accent color marks a hit.
export function runDots(bb) {
  return (bb.all_darts || []).map((d, i) => ({ n: `d${i}`, x: d.x, y: d.y, dot: true, scored: d.hit ? 1 : 0 }));
}
