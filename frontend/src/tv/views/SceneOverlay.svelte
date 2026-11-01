<script>
  // The effects of the scenes: confetti, a flash of the accent color or a banner, each with an optional text,
  // for the time the scene says. Several asked for at once are shown one after the other.
  import { sceneOverlayQueue, sceneOverlayShown } from '../../lib/stores/sceneOverlay.js';
  import ConfettiBurst from '../../lib/components/ConfettiBurst.svelte';

  let current = $derived($sceneOverlayQueue[0]);
  let wave = $state(0);
  const reduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;

  // The first one in the queue runs for its seconds; a confetti overlay lets a new burst fall every 2 seconds.
  $effect(() => {
    const item = current;
    if (!item) return;
    const done = setTimeout(sceneOverlayShown, item.seconds * 1000);
    const waves = item.animation === 'confetti' && !reduced ? setInterval(() => wave++, 2000) : null;
    return () => {
      clearTimeout(done);
      if (waves) clearInterval(waves);
    };
  });
</script>

{#if current}
  {#key current}
    <div class="overlay" class:flash={current.animation === 'flash' && !reduced} role="status" aria-live="polite">
      {#if current.animation === 'confetti' && !reduced}
        {#key wave}<ConfettiBurst />{/key}
      {/if}
      {#if current.text}
        <div class="text" class:banner={current.animation === 'banner'}>{current.text}</div>
      {/if}
    </div>
  {/key}
{/if}

<style>
  .overlay {
    position: fixed; inset: 0; z-index: 150; pointer-events: none;
    display: flex; align-items: center; justify-content: center;
  }
  .flash { animation: flash 0.7s ease-out 3; }
  .text {
    font-size: clamp(3rem, 12vw, 10rem); font-weight: 900; text-align: center; line-height: 1.05;
    color: var(--text); text-shadow: 0 6px 40px rgba(0, 0, 0, 0.7), 0 0 36px var(--accent);
    padding: 0 2rem; animation: pop 0.5s cubic-bezier(0.2, 1.4, 0.4, 1) both;
  }
  .text.banner {
    background: var(--surface); border: 2px solid var(--accent); border-radius: 1.5rem; padding: 1rem 3rem;
    box-shadow: 0 8px 40px rgba(0, 0, 0, 0.55), 0 0 40px color-mix(in srgb, var(--accent) 45%, transparent);
  }

  @keyframes flash {
    0%   { background: color-mix(in srgb, var(--accent) 55%, transparent); }
    100% { background: transparent; }
  }
  @keyframes pop {
    0%   { transform: scale(0.4); opacity: 0; }
    100% { transform: scale(1); opacity: 1; }
  }
  @media (prefers-reduced-motion: reduce) {
    .text { animation: none; }
  }
</style>
