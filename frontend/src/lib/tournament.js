import { api, apiJson } from './api.js';
import { t } from './i18n.js';

// The name of a round counted from the final: Final, Semi-final, Quarter-final, then Round of 16 and so on.
export function roundName(round, rounds) {
  const left = rounds - round;
  if (left === 1) return t('Final');
  if (left === 2) return t('Semi-final');
  if (left === 3) return t('Quarter-final');
  if (left === 4) return t('Round of 16');
  if (left === 5) return t('Round of 32');
  if (left === 6) return t('Preliminary round');
  return t('Round of {n}', { n: 2 ** left, f: 2 ** (left - 1) });
}

export function legsLabel(n) {
  return n > 1 ? t('First to {n} legs', { n }) : t('One leg');
}

// The number of rounds for this many players: the bracket is rounded up to the next power of two.
export function roundsFor(players) {
  let size = 2;
  while (size < players) size *= 2;
  return Math.log2(size);
}

// The bracket for these seats, shaped like the snapshot of a running tournament, for the setup page: the
// first round from the seats, a bye moves its player on, the later rounds are still empty.
export function previewSnap(seats, legsByRound) {
  // A match with one player is a bye only in the first round; later a slot is empty because it is not decided yet.
  const match = (a, b, first) => {
    const bye = first && !a !== !b;
    return { a: a || null, b: b || null, winner: bye ? (a || b) : null, bye, match_id: null, legs: null };
  };
  const rounds = [Array.from({ length: seats.length / 2 }, (_, i) => match(seats[2 * i], seats[2 * i + 1], true))];
  while (rounds[rounds.length - 1].length > 1) {
    const prev = rounds[rounds.length - 1];
    rounds.push(Array.from({ length: prev.length / 2 }, (_, i) => match(prev[2 * i].winner, prev[2 * i + 1].winner, false)));
  }
  return { active: true, rounds, config: { legs_by_round: legsByRound }, current: null, next: null, pending: null };
}

export async function drawSeats(players) {
  const res = await apiJson('POST', '/api/tournament/draw', { players });
  if (res.error) { alert(t(res.error)); return null; }
  return res.seats;
}

export async function startTournament(setup) {
  const res = await apiJson('POST', '/api/tournament/start', setup);
  if (res.error) { alert(t(res.error)); return false; }
  return true;
}

export function nextMatch() {
  return api('POST', '/api/tournament/next');
}

export async function abortTournament() {
  if (!confirm(t('Abort the tournament? The matches played and their statistics stay.'))) return false;
  await api('POST', '/api/tournament/abort');
  return true;
}

export function closeTournament() {
  return api('POST', '/api/tournament/close');
}
