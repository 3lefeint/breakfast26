import { derived } from 'svelte/store';
import { gameState } from './gameState.js';

// The Warm-up's own snapshot out of the /ws payload, the counterpart of the Black Belt store.
export const warmUp = derived(gameState, ($gameState) => $gameState.warm_up || null);
