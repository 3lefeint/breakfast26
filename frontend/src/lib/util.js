// Mirrors index.html/tv.html's cap() helper — capitalizes the first
// letter. Svelte auto-escapes interpolated text, so no esc() equivalent
// is needed here.
export function cap(s) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}
