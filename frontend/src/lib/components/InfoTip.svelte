<script>
  import { t } from '../i18n.js';
  // A small round "i" next to a title. Hover or keyboard focus shows the text in a pop-up; a click or tap keeps it
  // open (touch screens have no hover) until the next click elsewhere or Escape.
  let { children } = $props();

  let hover = $state(false);
  let pinned = $state(false);
  let root = $state(null);
  let dot = $state(null);
  let pos = $state('');
  let open = $derived(hover || pinned);

  // The pop-up is placed against the window, not against the button: next to a title on a phone the button sits
  // far to the right and a pop-up anchored to it would run out of the screen and widen the page.
  function place() {
    if (!dot) return;
    const r = dot.getBoundingClientRect();
    const width = Math.min(576, window.innerWidth - 32);
    const left = Math.max(16, Math.min(r.left, window.innerWidth - width - 16));
    pos = `top: ${r.bottom + 8}px; left: ${left}px; width: ${width}px;`;
  }
  $effect(() => { if (open) place(); });

  function outside(e) { if (root && !root.contains(e.target)) pinned = false; }
</script>

<svelte:window onclick={outside} onresize={place} onscroll={place} onkeydown={(e) => e.key === 'Escape' && (pinned = false)} />

<span class="info" bind:this={root} role="presentation" onmouseenter={() => (hover = true)} onmouseleave={() => (hover = false)}>
  <button type="button" class="dot" bind:this={dot} class:on={open} aria-label={t('Info')} aria-expanded={open}
    onclick={() => (pinned = !pinned)} onfocus={() => (hover = true)} onblur={() => (hover = false)}>i</button>
  {#if open}
    <div class="pop" role="tooltip" style={pos}>{@render children()}</div>
  {/if}
</span>

<style>
  .info { position: relative; display: inline-flex; vertical-align: middle; margin-left: 0.5rem; }
  .dot {
    width: 1.15rem; height: 1.15rem; border-radius: 50%; padding: 0; cursor: pointer;
    font-family: inherit; font-size: 0.7rem; font-weight: 700; font-style: italic; line-height: 1;
    display: flex; align-items: center; justify-content: center;
    background: var(--glass); border: 1px solid var(--glass-border); color: var(--muted);
    transition: color 0.15s, border-color 0.15s;
  }
  .dot:hover, .dot.on { color: var(--accent); border-color: var(--accent); }
  .pop {
    position: fixed; z-index: 50; max-height: 70vh; box-sizing: border-box; overflow-y: auto;
    padding: 1rem 1.2rem; border-radius: 14px; background: var(--bg, #0f1115); border: 1px solid var(--glass-border);
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.5); font-size: 0.85rem; font-weight: 400; letter-spacing: normal;
    line-height: 1.45; overflow-wrap: anywhere; color: var(--text); text-align: left; font-style: normal;
  }
  .pop :global(p) { margin: 0 0 0.7rem; font-size: inherit; color: inherit; }
  .pop :global(ul) { margin: 0.3rem 0 0.2rem 1.1rem; padding: 0; }
  .pop :global(li) { margin-bottom: 0.3rem; }
  .pop :global(strong) { color: var(--accent); font-weight: 700; }
</style>
