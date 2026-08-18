<script>
  // Shared header used identically across Home/TV/Audio — logo (always
  // links back to Home) + an optional centered title + a contextual
  // right-side snippet per app (sound toggle on TV/Audio, connection
  // status, etc). Frosted-glass treatment (backdrop-filter +
  // accent-tinted border glow) instead of a flat surface — reads as
  // more "modern framework" without touching the underlying color
  // tokens (still just --accent/--surface/--border, per the app's
  // existing dark-only/swappable-accent theme system).
  //
  // glowColor ('green' | 'yellow' | 'red' | null) swaps that subtle
  // accent-tinted underline for a much more prominent colored glow —
  // used by /tv to make the board's current status genuinely hard to
  // miss instead of a small footer dot nobody's looking at while
  // throwing. null keeps the default, app-wide accent glow.
  let { left, right, title = '', glowColor = null } = $props();
</script>

<header class:glow-green={glowColor === 'green'} class:glow-yellow={glowColor === 'yellow'} class:glow-red={glowColor === 'red'}>
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
    transition: box-shadow 0.3s;
    flex-shrink: 0;
    position: relative;
    z-index: 20;
  }
  /* A solid colored edge plus a soft blurred bleed below it — meant to
     read as a glow, not just a colored line, so it's catchable in
     peripheral vision while actually looking at the dartboard. */
  header.glow-green {
    box-shadow: 0 2px 0 0 var(--green), 0 10px 28px -6px color-mix(in srgb, var(--green) 65%, transparent);
  }
  header.glow-yellow {
    box-shadow: 0 2px 0 0 var(--yellow), 0 10px 28px -6px color-mix(in srgb, var(--yellow) 65%, transparent);
  }
  header.glow-red {
    box-shadow: 0 2px 0 0 var(--red), 0 10px 28px -6px color-mix(in srgb, var(--red) 65%, transparent);
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
