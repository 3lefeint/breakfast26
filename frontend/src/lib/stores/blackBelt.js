import { derived } from 'svelte/store';
import { gameState } from './gameState.js';

// Black Belt's own snapshot out of the /ws payload, the counterpart of the Field Training store.
export const blackBelt = derived(gameState, ($gameState) => $gameState.black_belt || null);
