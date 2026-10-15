import { derived } from 'svelte/store';
import { gameState } from './gameState.js';

// The snapshot of an X01 match played in Breakfast out of the /ws payload (the `x01` part). The
// live score of such a match comes through `gameState.game` like that of any X01 match.
export const x01Own = derived(gameState, ($gameState) => $gameState.x01 || null);
