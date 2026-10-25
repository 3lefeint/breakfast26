import { get, writable } from 'svelte/store';

// The admin of the circle (see relay/PROTOCOL.md, "Admin"): the page talks to the relay directly from the browser. Only the address
// of the relay is remembered in this browser (it is no secret); the password is typed per session and the token the login answers
// lives in memory only, so it is gone when the page is closed and nothing of it is stored on an installation.
const KEY = 'adminRelay';

function remembered() {
  try {
    return localStorage.getItem(KEY) || '';
  } catch (e) {
    return '';
  }
}

// The address of the relay as the admin routes need it: https://host (a wss:// address from the settings is turned around).
export function relayBase(text) {
  let url = (text || '').trim().replace(/\/+$/, '');
  if (url.startsWith('wss://')) url = 'https://' + url.slice(6);
  else if (url.startsWith('ws://')) url = 'http://' + url.slice(5);
  return /^https?:\/\/[^\s/]+$/.test(url) ? url : '';
}

export const adminRelay = writable(remembered());
export const adminLoggedIn = writable(false);

let token = null;
let expiresAt = 0;

export class AdminError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.status = status;
  }
}

async function request(url, options) {
  let res;
  try {
    res = await fetch(url, options);
  } catch (e) {
    throw new AdminError('the relay is not reachable');
  }
  let body = {};
  try {
    body = await res.json();
  } catch (e) { /* no body */ }
  if (!res.ok) throw new AdminError(body.error || `the relay answered ${res.status}`, res.status);
  return body;
}

export async function adminLogin(relay, password) {
  const base = relayBase(relay);
  if (!base) throw new AdminError('enter the address of the relay, e.g. https://relay.example.com');
  const body = await request(`${base}/admin/login`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password }),
  });
  token = body.token;
  expiresAt = body.expires_at;
  try { localStorage.setItem(KEY, base); } catch (e) { /* remembering is optional */ }
  adminRelay.set(base);
  adminLoggedIn.set(true);
}

export function adminLogout() {
  token = null;
  expiresAt = 0;
  adminLoggedIn.set(false);
}

export function adminForget() {
  adminLogout();
  try { localStorage.removeItem(KEY); } catch (e) { /* nothing to forget */ }
  adminRelay.set('');
}

// A call to an admin route; the answer is the JSON. A login that ran out (or was refused) ends the session.
export async function adminCall(method, path, body) {
  if (!token || Date.now() >= expiresAt) {
    adminLogout();
    throw new AdminError('log in first', 401);
  }
  try {
    return await request(`${get(adminRelay)}${path}`, {
      method,
      headers: { Authorization: `Bearer ${token}`, ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (e) {
    if (e.status === 401) adminLogout();
    throw e;
  }
}

// "3 min ago" for a time in milliseconds, "never" for none.
export function ago(ms, t) {
  if (!ms) return t('never');
  const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
  if (s < 90) return t('just now');
  const m = Math.round(s / 60);
  if (m < 90) return t('{n} min ago', { n: m });
  const h = Math.round(m / 60);
  if (h < 36) return t('{n} h ago', { n: h });
  return t('{n} days ago', { n: Math.round(h / 24) });
}

// The parts of a version like "1.11.1" as numbers; anything that is not a version gives null.
function versionParts(version) {
  const m = /^v?(\d+(?:\.\d+)*)/.exec(String(version || '').trim());
  return m ? m[1].split('.').map(Number) : null;
}

// Negative when version a is older than b, positive when newer, 0 when equal or not comparable.
export function compareVersions(a, b) {
  const x = versionParts(a);
  const y = versionParts(b);
  if (!x || !y) return 0;
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    const d = (x[i] || 0) - (y[i] || 0);
    if (d) return d;
  }
  return 0;
}

// The newest version among the sites (each has a `version`), '' when none reported one.
export function newestVersion(sites) {
  let newest = '';
  for (const site of sites) {
    if (versionParts(site.version) && (!newest || compareVersions(site.version, newest) > 0)) newest = site.version;
  }
  return newest;
}
