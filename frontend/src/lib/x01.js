import { api, apiJson } from './api.js';
import { t } from './i18n.js';

export const START_SCORES = [101, 201, 301, 501, 701, 1001];
export const MODES = ['straight', 'double', 'master'];
export const MAX_LEGS = 25;

// Start the match that just finished once more: same players, same rules.
export async function rematch(x) {
  const res = await apiJson('POST', '/api/x01/start', {
    players: x.order,
    start: x.setup.start,
    in_mode: x.setup.in_mode,
    out_mode: x.setup.out_mode,
    legs: x.setup.legs,
    bull_off: x.setup.bull_off,
  });
  if (res.error) alert(t(res.error));
  return !res.error;
}

// Clear the finished match so a new one can be set up.
export function stopGame() {
  return api('POST', '/api/x01/stop');
}

export function inLabel(mode) {
  return mode === 'double' ? t('Double in') : mode === 'master' ? t('Master in') : t('Straight in');
}

export function outLabel(mode) {
  return mode === 'double' ? t('Double out') : mode === 'master' ? t('Master out') : t('Straight out');
}

// The rules for the chips on the screens, without the start score (the screens show that already):
// the in mode when it is not a straight one, the out mode, the legs to win.
export function ruleChips(x) {
  const rules = x?.rules || {};
  return [
    ...(rules.in_mode && rules.in_mode !== 'straight' ? [inLabel(rules.in_mode)] : []),
    outLabel(rules.out_mode),
    rules.legs > 1 ? t('First to {n} legs', { n: rules.legs }) : t('One leg'),
  ];
}
