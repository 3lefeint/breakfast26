import { api, apiJson } from './api.js';

// Start the game that just finished once more: same players in the same order, same options.
export async function rematch(tb) {
  const res = await apiJson('POST', '/api/target-battle/start', {
    players: tb.order,
    rounds: tb.setup.rounds,
    scoring: tb.setup.scoring,
    tiebreak: tb.setup.tiebreak,
    targets: tb.setup.targets,
  });
  if (res.error) alert(res.error);
  return !res.error;
}

// Clear the finished game so a new one can be set up.
export function stopGame() {
  return api('POST', '/api/target-battle/stop');
}

export const SCORING_LABELS = {
  standard: 'Standard: single 1, double 2, triple 3',
  singles: 'Singles only',
  doubles: 'Doubles only',
  triples: 'Triples only',
};

export const SCORING_SHORT = {
  standard: 'Standard',
  singles: 'Singles only',
  doubles: 'Doubles only',
  triples: 'Triples only',
};

// The players, best first; players on the same total keep their seating order.
export function ranked(tb) {
  return [...(tb.players || [])].sort((a, b) => b.score - a.score);
}

// Every dart of the round as a marker for the board: in the color of its player, with the
// player's ring if the color is close to another one, and what it scored as its label.
export function boardDarts(tb) {
  const darts = [];
  for (const p of tb.players || []) {
    (tb.round_darts?.[p.name] || []).forEach((d, i) => {
      darts.push({ n: `${p.name}-${i}`, label: d.points, x: d.x, y: d.y, color: p.color, ring: p.ring, avatar: { name: p.name, color: p.color } });
    });
  }
  return darts;
}
