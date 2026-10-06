// How a finishing place is drawn: 1st is the full accent, 2nd and 3rd step
// down from it, anything lower is a neutral. Shared so every Elimination
// chart reads the same.
import { t } from '../../../lib/i18n.js';
export const RANKS = [
  { key: 'first', place: 1, label: t('1st'), color: 'var(--accent)', ink: 'var(--bg)' },
  { key: 'second', place: 2, label: t('2nd'), color: 'color-mix(in srgb, var(--accent) 55%, var(--surface))', ink: 'var(--text)' },
  { key: 'third', place: 3, label: t('3rd'), color: 'color-mix(in srgb, var(--accent) 30%, var(--surface))', ink: 'var(--text)' },
  { key: 'other', place: 4, label: t('Lower'), color: 'var(--border)', ink: 'var(--text)' },
];

export function rankForPlace(place) {
  return RANKS[Math.min(place, 4) - 1];
}
