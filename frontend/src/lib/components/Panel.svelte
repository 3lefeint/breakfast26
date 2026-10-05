<script>
  // A glass panel: the container of a block of content, with an optional title.
  let { title = '', children } = $props();
</script>

<section class="panel">
  {#if title}<h3>{title}</h3>{/if}
  {@render children?.()}
</section>

<style>
  .panel {
    padding: 1.5rem; margin-bottom: 1.25rem; border-radius: 16px;
    background: var(--glass); border: 1px solid var(--glass-border);
    backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur);
    box-shadow: var(--glass-shadow);
  }
  h3 {
    font-size: 0.8rem; font-weight: 700; color: var(--muted);
    letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 1rem;
  }
</style>
