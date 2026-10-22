import { t } from './i18n.js';

// The stored form of a name typed by the user: names are stored in lower case (names.py in the backend).
export const storedName = (s) => s.trim().toLowerCase();

// A player name as the interface shows it: in upper case, names are stored in lower case. The placeholder of a deleted
// player ("deleted player", "deleted player 2") is translated, a guest of another site ("name@site") shows the site in
// brackets.
export function shownName(s) {
  if (!s) return s;
  const deleted = /^deleted player( \d+)?$/.exec(s);
  if (deleted) return (t('Deleted player') + (deleted[1] ?? '')).toUpperCase();
  const guest = /^(.+)@([^@]+)$/.exec(s);
  return (guest ? `${guest[1]} (${guest[2]})` : s).toUpperCase();
}

// A date and time as dd/mm/yyyy hh:mm in the 24-hour format, whatever the locale of the browser.
export function formatDateTime(iso) {
  return new Date(iso).toLocaleString('en-GB', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
  }).replace(', ', ' ');
}

// The board manager's status when the board stopped (camera standby time): the raw one, or the one made from the event.
export const isBoardStopped = (status) => status === 'Stopped' || status === 'Board Stopped';
