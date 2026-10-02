import { derived } from 'svelte/store';
import { gameState } from './gameState.js';

// The online match (relay session) out of the /ws payload: null while none is open,
// otherwise {phase, code, site, host, lobby, local_players, match, paused, decision,
// result, message, connected}.
export const online = derived(gameState, ($gameState) => $gameState.online || null);
