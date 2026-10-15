import { derived } from 'svelte/store';
import { gameState } from './gameState.js';

// The snapshot of the X01 tournament out of the /ws payload (the `tournament` part): {active: false}
// without one, else the phase, the rounds with their matches, the match in play, a result that waits and
// the pairing that is next.
export const tournament = derived(gameState, ($gameState) => $gameState.tournament || null);
