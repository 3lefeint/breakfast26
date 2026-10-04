import { derived } from 'svelte/store';
import { gameState } from './gameState.js';

// Target Battle's own snapshot out of the /ws payload, the counterpart of the elimination store.
export const targetBattle = derived(gameState, ($gameState) => $gameState.target_battle || null);
