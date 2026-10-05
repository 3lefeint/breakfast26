// Helpers for the achievement badges and the profile view.

// The exported motifs (tools/generate_badges.py --export) by achievement id.
const motifFiles = import.meta.glob('./assets/badges/*.png', { eager: true, import: 'default' });
const motifs = {};
for (const [path, url] of Object.entries(motifFiles)) {
  motifs[path.split('/').pop().replace(/\.png$/, '')] = url;
}

export function motifUrl(id) {
  return motifs[id] || null;
}

// Texts come in several languages, {en, de}. The UI is English until the language
// switch exists.
export function localized(texts) {
  return texts ? texts.en : null;
}

export function isEarned(item) {
  return item.tier > 0;
}

const GROUPS = [
  ['general', 'General'],
  ['x01', 'X01'],
  ['elimination', 'Elimination'],
  ['killer', 'Killer'],
  ['target_battle', 'Target Battle'],
  ['field_training', 'Field Training'],
  ['easter_egg', 'Easter eggs'],
];

// Sections by game mode, in the order above, each split into what is earned (newest
// first) and what is still open. A secret achievement stays out of its mode until it
// is earned: the secret ones that are still open share a last section, so it does not
// show which mode they belong to. Empty sections are left out.
export function groupAchievements(items) {
  const sections = GROUPS.map(([key, label]) => ({ key, label, earned: [], open: [] }));
  const secret = { key: 'secret', label: 'Secret', earned: [], open: [] };
  for (const item of items) {
    if (item.hidden && !isEarned(item)) {
      secret.open.push(item);
      continue;
    }
    const section = sections.find((s) => s.key === item.mode) || sections[0];
    (isEarned(item) ? section.earned : section.open).push(item);
  }
  for (const section of sections) {
    section.earned.sort((a, b) => (b.earned_at || '').localeCompare(a.earned_at || ''));
  }
  return [...sections, secret]
    .filter((s) => s.earned.length + s.open.length > 0)
    .map((s) => ({ ...s, total: s.earned.length + s.open.length }));
}

// "3 / 10" for a counter on its way to the next tier, "" for everything else.
export function progressText(item) {
  if (item.progress == null || item.next == null) return '';
  return `${item.progress} / ${item.next}`;
}

// How many players have the tier the badge shows, "" while that is not known.
export function rarityText(item) {
  if (item.percent == null) return '';
  const share = item.percent > 0 && item.percent < 1 ? '<1' : String(Math.round(item.percent));
  return item.tiers
    ? `${share}% of players reached tier ${Math.max(item.tier, 1)}`
    : `${share}% of players have this`;
}
