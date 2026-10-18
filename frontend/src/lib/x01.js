import { alertDialog } from './confirm.js';
import { api, apiJson } from './api.js';
import { t } from './i18n.js';

export const START_SCORES = [101, 201, 301, 501, 701, 1001];
export const MODES = ['straight', 'double', 'master'];
export const MAX_LEGS = 25;
// The stages of a computer opponent in X01, weakest first, numbered 1 to 5.
export const BOT_STAGE_COUNT = 5;
export const botStageName = (stage) => [t('Beginner'), t('Casual'), t('Advanced'), t('Club player'), t('Pro')][stage - 1];
// The choices for the max rounds: no limit, or the rounds after which a bull-off decides the leg.
export const MAX_ROUNDS_CHOICES = [null, 15, 25, 50];

// Start the match that just finished once more: same players, same rules.
export async function rematch(x) {
  const res = await apiJson('POST', '/api/x01/start', {
    players: x.order,
    start: x.setup.start,
    in_mode: x.setup.in_mode,
    out_mode: x.setup.out_mode,
    legs: x.setup.legs,
    bull_off: x.setup.bull_off,
    max_rounds: x.setup.max_rounds,
    bots: Object.fromEntries(x.players.filter((p) => p.bot).map((p) => [p.name, p.bot])),
  });
  if (res.error) alertDialog(t(res.error));
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
    ...(rules.max_rounds ? [t('Max Rounds: {n}', { n: rules.max_rounds })] : []),
  ];
}
