import { derived } from 'svelte/store';
import { gameState } from './gameState.js';

// Checkout Training's own snapshot out of the /ws payload, the counterpart of the Field Training store.
export const checkoutTraining = derived(gameState, ($gameState) => $gameState.checkout_training || null);
