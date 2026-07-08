<script>
  // Shared header used identically across Home/TV/Audio — logo (always
  // links back to Home) + an optional centered title + a contextual
  // right-side snippet per app (sound toggle on TV/Audio, connection
  // status, etc). Frosted-glass treatment (backdrop-filter +
  // accent-tinted border glow) instead of a flat surface — reads as
  // more "modern framework" without touching the underlying color
  // tokens (still just --accent/--surface/--border, per the app's
  // existing dark-only/swappable-accent theme system).
  let { left, right, title = '' } = $props();
</script>

<header>
  <div class="left-group">
    <a class="brand-link" href="/" title="Breakfast — back to home">
      <img src="/static/breakfast-header-sport-dark-tight.png" alt="Breakfast">
    </a>
    {@render left?.()}
  </div>
  <div class="title">{title}</div>
  <div class="right">
    {@render right?.()}
  </div>
</header>

<style>
  header {
    width: 100%;
    box-sizing: border-box;
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    align-items: center;
    padding: 0.65rem 1.25rem;
    background: color-mix(in srgb, var(--surface) 80%, transparent);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    border-bottom: 1px solid var(--border);
    box-shadow: 0 1px 0 0 color-mix(in srgb, var(--accent) 12%, transparent);
    flex-shrink: 0;
    position: relative;
    z-index: 20;
  }
  .left-group { display: flex; align-items: center; gap: 0.6rem; justify-self: start; }
  .brand-link { display: inline-flex; align-items: center; line-height: 0; transition: opacity 0.15s; }
  .brand-link:hover { opacity: 0.85; }
  .brand-link img { height: 32px; width: auto; display: block; }
  .title {
    justify-self: center; text-align: center;
    font-weight: 600; font-size: 0.95rem; color: var(--text);
    white-space: nowrap;
  }
  .right { display: flex; align-items: center; gap: 1rem; justify-self: end; }
</style>
