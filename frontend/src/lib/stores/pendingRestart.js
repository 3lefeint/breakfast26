import { writable } from 'svelte/store';

// The settings that were saved and need a restart to apply (their config keys, `mqtt.host`). Kept here, not in
// Settings, so the notice is still there after another page was shown in between.
export const pendingRestart = writable([]);
