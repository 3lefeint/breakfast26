import { derived } from 'svelte/store';
import { gameState } from './gameState.js';

// Killer's own snapshot out of the /ws payload, the counterpart of the elimination store.
export const killer = derived(gameState, ($gameState) => $gameState.killer || null);
