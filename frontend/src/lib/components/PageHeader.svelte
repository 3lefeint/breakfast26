<script>
  // The heading of a page of the Home app: the title, an optional line below it and, on sub-pages, a
  // way back. The sidebar is the main navigation; the back button leads one level up (default: the
  // Play page).
  import Icon from './Icon.svelte';

  let { title, subtitle = '', back = '#home' } = $props();
</script>

<div class="page-header">
  <a class="back" href={back} aria-label={back === '#home' ? 'Back to Play' : 'Back'}><Icon name="back" size={20} stroke={2.2} /></a>
  <div class="text">
    <h1>{title}</h1>
    {#if subtitle}<p>{subtitle}</p>{/if}
  </div>
</div>

<style>
  .page-header { display: flex; align-items: center; gap: 1rem; margin-bottom: 1.75rem; }
  .back {
    display: flex; align-items: center; justify-content: center; flex-shrink: 0;
    width: 2.6rem; height: 2.6rem; border-radius: 12px; color: var(--muted);
    background: var(--glass); border: 1px solid var(--glass-border);
    backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur);
    transition: color 0.15s, border-color 0.15s, transform 0.15s;
  }
  .back:hover { color: var(--accent); border-color: var(--accent); transform: translateX(-2px); }
  h1 { font-size: clamp(1.8rem, 3.4vw, 2.6rem); font-weight: 800; letter-spacing: -0.02em; line-height: 1.1; }
  p { margin-top: 0.3rem; font-size: 1.1rem; color: color-mix(in srgb, var(--text) 72%, transparent); }
</style>
