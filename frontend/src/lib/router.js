import { writable } from 'svelte/store';

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
