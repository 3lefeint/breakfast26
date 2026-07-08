<script>
  // Small back-arrow + title row for Home's sub-pages (Elimination/
  // Players/Stats/Settings) — replaces the old always-visible 5-item nav
  // bar, which duplicated the hub cards. The hub cards are the primary
  // navigation now; this is just "how do I get back".
  let { title } = $props();
</script>

<div class="page-header">
  <a class="back" href="#home" aria-label="Back to Home">
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M15 18l-6-6 6-6" />
    </svg>
  </a>
  <h1>{title}</h1>
</div>

<style>
  .page-header {
    display: flex; align-items: center; gap: 0.75rem;
    margin-bottom: 1.25rem;
  }
  .back {
    display: flex; align-items: center; justify-content: center;
    width: 2.25rem; height: 2.25rem; border-radius: 999px;
    color: var(--muted); background: var(--surface); border: 1px solid var(--border);
    transition: color 0.15s, border-color 0.15s, transform 0.15s;
  }
  .back:hover { color: var(--accent); border-color: var(--accent); transform: translateX(-2px); }
  h1 { font-size: 1.35rem; font-weight: 800; letter-spacing: -0.01em; }
</style>
