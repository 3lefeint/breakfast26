import { writable } from 'svelte/store';

// Achievements that were just earned and wait to be shown on /tv, oldest first.
export const achievementQueue = writable([]);

export function announceAchievement(message) {
  achievementQueue.update((queue) => [...queue, message]);
}

// The banner calls this when it has finished showing the first one.
export function achievementShown() {
  achievementQueue.update((queue) => queue.slice(1));
}
