import { writable } from 'svelte/store';

// Polls /api/health for the footer's MQTT/Autodarts connection dots,
// version info, and (on /tv) the abandoned-match warning (matchActive +
// secondsSinceActivity) — same 30s interval as the original
// index.html/tv.html. Shared between Home and TV.
export const health = writable({
  mqttOk: null, autodartsOk: null, version: null, releaseDate: null,
  matchActive: false, secondsSinceActivity: null,
});

let timer = null;

async function poll() {
  try {
    const h = await fetch('/api/health').then((r) => r.json());
    health.set({
      mqttOk: h.mqtt?.connected ?? null,
      autodartsOk: h.autodarts?.connected ?? null,
      version: h.version ?? null,
      releaseDate: h.release_date ?? null,
      matchActive: h.autodarts?.match_active ?? false,
      secondsSinceActivity: h.autodarts?.seconds_since_activity ?? null,
    });
  } catch (_) {
    // keep last known state on a transient fetch failure
  }
}

export function startHealthPolling() {
  poll();
  if (timer) clearInterval(timer);
  timer = setInterval(poll, 30000);
}
