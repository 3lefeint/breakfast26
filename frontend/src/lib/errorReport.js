// Reports an uncaught error of the page to the backend: its name and where it happened, never its
// message. The backend drops it unless usage reporting is switched on (Settings → Usage reports).

const MAX_PER_PAGE = 5;
let sent = 0;

function frames(stack) {
  const out = [];
  for (const m of String(stack || '').matchAll(/([^\s/()@]+?):(\d+):(\d+)/g)) {
    out.push(`${m[1]}:${m[2]}:${m[3]}`);
    if (out.length >= 8) break;
  }
  return out;
}

function report(error, file, line, col) {
  if (sent >= MAX_PER_PAGE) return;
  sent += 1;
  const list = frames(error && error.stack);
  if (!list.length && file) list.push(`${String(file).split('?')[0].split('/').pop()}:${line || 0}:${col || 0}`);
  fetch('/api/telemetry/client-error', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: (error && error.name) || 'Error', frames: list }),
    keepalive: true,
  }).catch(() => {});
}

export function installErrorReport() {
  window.addEventListener('error', (e) => report(e.error, e.filename, e.lineno, e.colno));
  window.addEventListener('unhandledrejection', (e) => report(e.reason));
}
