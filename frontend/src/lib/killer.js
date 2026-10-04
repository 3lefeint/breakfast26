import { api, apiJson } from './api.js';
import { cap } from './util.js';

// Start the game that just finished once more: same players in the same order, same options. Every
// player gets a new number.
export async function rematch(k) {
  const res = await apiJson('POST', '/api/killer/start', {
    players: k.order,
    own_goal: k.setup.own_goal,
    singles: k.setup.singles,
  });
  if (res.error) alert(res.error);
  return !res.error;
}

// Clear the finished game so a new one can be set up.
export function stopGame() {
  return api('POST', '/api/killer/stop');
}

// The rules that are on, for the chips on the screens: which darts take a life, and the own goal.
export function ruleChips(k) {
  const rules = k?.rules || {};
  return [rules.singles ? 'Singles and doubles take lives' : 'Only doubles take lives',
          ...(rules.own_goal ? ['Own goals cost a life'] : [])];
}

// A dart of the board view as the chip shows it: its field, or "Miss" outside every field.
export function dartLabel(dart) {
  if (!dart || !dart.field || /^M\d*$/i.test(dart.field)) return 'Miss';
  return dart.field;
}

// One event of a turn as a line of text.
export function eventText(e) {
  const who = cap(e.player);
  const victim = e.victim ? cap(e.victim) : '';
  switch (e.kind) {
    case 'killer': return `${who} is a killer`;
    case 'hit': return `${who} hits ${victim}, ${e.lives} left`;
    case 'own_goal': return `${who} own goal, ${e.lives} left`;
    case 'out': return `${victim} is out`;
    default: return '';
  }
}

// What the board shows. The field of every number that belongs to a player is colored in the
// player's color for the whole game, darkened once the player is out. On top of that, what is open
// for the player who is up. Not a killer yet: the double of the own number. A killer: the fields that
// take a life from each opponent still in (doubles, singles too with that option), and with own goals
// on a warning on the own number.
export function boardZones(k) {
  const players = k?.players || [];
  const zones = players.map((p) => (p.out
    ? { n: p.number, parts: 'all', level: 'dead' }
    : { n: p.number, color: p.color, parts: 'all', level: 'owned' }));
  const me = players.find((p) => p.current);
  if (!me || k.state !== 'playing' || me.out) return zones;
  if (!me.killer) return [...zones, { n: me.number, color: me.color, parts: ['double'], level: 'strong' }];
  const parts = k.rules?.singles ? ['double', 'outerSingle', 'innerSingle'] : ['double'];
  for (const p of players) {
    if (p !== me && !p.out) zones.push({ n: p.number, color: p.color, parts, level: 'strong' });
  }
  if (k.rules?.own_goal) zones.push({ n: me.number, parts, level: 'danger' });
  return zones;
}
