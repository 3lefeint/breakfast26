// Mirrors index.html's api() fetch wrapper — plain REST calls, no extra
// data-fetching layer needed since the backend API surface doesn't change.
export async function api(method, url, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  await fetch(url, opts);
}

// Same, but returns the JSON answer — for calls that can come back with {error}.
export async function apiJson(method, url, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(url, opts);
  return res.json();
}
