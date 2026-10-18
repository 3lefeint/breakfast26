import { alertDialog } from './confirm.js';
import { api, apiJson } from './api.js';
import { t } from './i18n.js';

// The name of a station of the run, by the kind of field it has.
export function stationName(kind) {
  return {
    big: t('Big singles'), bull: t('Bull'), small: t('Small singles'),
    double: t('Doubles'), eye: t('Bull\'s eye'), triple: t('Triples'),
  }[kind] || kind;
}

// The part of the board a field is, for the line under the number that is up.
export function ringName(kind) {
  return {
    big: t('Big single'), bull: t('Bull'), small: t('Small single'),
    double: t('Double'), eye: t('Bull\'s eye'), triple: t('Triple'),
  }[kind] || kind;
}

// A field of the run in a few characters: Big 7, Small 7, D7, T7, Bull.
export function fieldLabel(kind, number) {
  switch (kind) {
    case 'big': return t('Big {n}', { n: number });
    case 'small': return t('Small {n}', { n: number });
    case 'double': return `D${number}`;
    case 'triple': return `T${number}`;
    default: return ringName(kind);
  }
}

// The part of the board to hit, to light on the virtual board: the ring of the field, not only the number.
export function zonesFor(target) {
  if (!target) return [];
  if (target.kind === 'bull') return [{ n: 25, level: 'strong' }, { n: 50, level: 'strong' }];
  if (target.kind === 'eye') return [{ n: 50, level: 'strong' }];
  const part = { big: 'outerSingle', small: 'innerSingle', double: 'double', triple: 'triple' }[target.kind];
  return [{ n: target.number, parts: [part], level: 'strong' }];
}

// The kinds of field a run can go over, in the order the setup lists them.
export const KINDS = ['big', 'small', 'double', 'triple', 'bull', 'eye'];

// What a run goes over in words: all of it, or the picked stations.
export function modeLabel(kinds) {
  return !kinds || kinds.length === KINDS.length ? t('All') : kinds.map(stationName).join(', ');
}

export async function startRun(setup) {
  const res = await apiJson('POST', '/api/warm-up/start', setup);
  if (res.error) alertDialog(t(res.error));
  return !res.error;
}

// Another run with the same player and stations.
export function rematch(wu) {
  return startRun(wu.setup);
}

// Clear the run so a new one can be set up. Whatever was thrown stays saved.
export function stopRun() {
  return api('POST', '/api/warm-up/stop');
}

// End the run: the darts thrown so far are kept.
export function finishRun() {
  return api('POST', '/api/warm-up/finish');
}

export function undoTurn() {
  return api('POST', '/api/warm-up/undo');
}

// Every dart of the run as a small dot for the board: the accent color marks a hit.
export function runDots(wu) {
  return (wu.all_darts || []).map((d, i) => ({ n: `d${i}`, x: d.x, y: d.y, dot: true, scored: d.hit ? 1 : 0 }));
}
