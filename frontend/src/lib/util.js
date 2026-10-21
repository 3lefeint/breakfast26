// Mirrors the cap() helper of the former index.html and tv.html — capitalizes the first
// letter. Svelte auto-escapes interpolated text, so no esc() equivalent
// is needed here.
export function cap(s) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

// A date and time as dd/mm/yyyy hh:mm in the 24-hour format, whatever the locale of the browser.
export function formatDateTime(iso) {
  return new Date(iso).toLocaleString('en-GB', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
  }).replace(', ', ' ');
}

// The board manager's status when the board stopped (camera standby time): the raw one, or the one made from the event.
export const isBoardStopped = (status) => status === 'Stopped' || status === 'Board Stopped';
