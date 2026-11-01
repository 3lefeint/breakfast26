import { writable } from 'svelte/store';

// The overlays that scenes asked for and wait to be shown in the TV view, oldest first.
export const sceneOverlayQueue = writable([]);

export function announceSceneOverlay(message) {
  sceneOverlayQueue.update((queue) => [...queue, message]);
}

// The overlay calls this when it has finished showing the first one.
export function sceneOverlayShown() {
  sceneOverlayQueue.update((queue) => queue.slice(1));
}
