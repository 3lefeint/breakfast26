import { derived } from 'svelte/store';
import { gameState } from './gameState.js';

// Field Training's own snapshot out of the /ws payload, the counterpart of the Target Battle store.
export const fieldTraining = derived(gameState, ($gameState) => $gameState.field_training || null);
