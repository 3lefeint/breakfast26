import { derived } from 'svelte/store';
import { gameState } from './gameState.js';

// Derives Elimination's own snapshot straight out of the /ws payload —
// a thin pass-through today, but the single place to extend once the
// Home/TV app rebuilds (battle-plan steps 5/6) need shared derived
// fields (e.g. "is match over", "next player") instead of each app
// recomputing them.
export const elimination = derived(gameState, ($gameState) => $gameState.elimination || null);
