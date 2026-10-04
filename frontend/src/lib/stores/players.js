import { derived } from 'svelte/store';
import { gameState } from './gameState.js';

// Derives the Players-tab/known-chips shape from the raw /ws payload once,
// so Home and TV apps don't each re-derive win/audio lookups themselves.
export const players = derived(gameState, ($gameState) => {
  const known = $gameState.known_players || [];
  const wins = $gameState.elimination_wins || {};
  const x01Wins = $gameState.x01_wins || {};
  const missingAudio = new Set($gameState.players_missing_audio || []);
  const hidden = $gameState.hidden_players || [];
  const colors = $gameState.player_colors || {};
  return {
    known,
    hidden,
    winsFor: (name) => wins[name] || 0,
    x01WinsFor: (name) => x01Wins[name] || 0,
    missingAudio: (name) => missingAudio.has(name),
    colorFor: (name) => colors[name] || null,
  };
});
