import { writable } from 'svelte/store';
import { primeAutoplay } from '../tv/lib/audio.js';

// Small hash-based router for the card/hub home navigation.
// Not SvelteKit's router — just enough to make views deep-linkable and let
// the browser back/forward buttons work, which the "Done -> Elimination
// tab" behavior then piggybacks on.
function currentRoute() {
  return (location.hash || '#home').slice(1);
}

export const route = writable(currentRoute());

if (typeof window !== 'undefined') {
  window.addEventListener('hashchange', () => route.set(currentRoute()));
}

export function navigate(path) {
  location.hash = path;
}

// The TV view is a route of this app, not a page of its own: the click that starts a game and the audio
// player are in the same document, so the browser lets the voice calls play (a new page would start locked again).
export function openTv() {
  primeAutoplay();
  location.hash = 'tv';
}
