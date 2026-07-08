<script>
  // Fired once when the version number in the Home footer is tapped
  // DEV_TAP_THRESHOLD times (see home/App.svelte's onVersionTap()) — a
  // centered "Dev Mode" pop-in plus a burst of falling dickbutts, mirroring
  // ConfettiBurst.svelte's win-celebration pattern (pure CSS keyframes, no
  // library). The parent removes this component after ~2.5s.
  import dickbuttUrl from '../assets/dickbutt.png';

  const COUNT = 50;

  const pieces = Array.from({ length: COUNT }, (_, i) => ({
    id: i,
    left: Math.random() * 100,
    delay: Math.random() * 0.4,
    duration: 1.6 + Math.random() * 1.0,
    // Full, independently randomized spins (each direction, several full
    // turns) rather than a gentle tilt, so the pieces visibly tumble
    // differently from each other instead of all drifting down flat.
    rotate: (Math.random() - 0.5) * 1080,
    size: 24 + Math.random() * 100,
    // Shimmer runs as a second, independent animation alongside the fall
    // (different CSS property — filter, not transform — so they don't
    // conflict) — randomized delay/duration per piece so they don't all
    // pulse in lockstep.
    shimmerDelay: Math.random() * 0.6,
    shimmerDuration: 0.5 + Math.random() * 0.6,
  }));
</script>

<div class="dev-unlock-celebration" aria-hidden="true">
  <div class="dev-mode-text">Dev Mode</div>
  {#each pieces as p (p.id)}
    <img
      class="piece"
      src={dickbuttUrl}
      alt=""
      style="left:{p.left}%; width:{p.size}px; --rot:{p.rotate}deg;
             animation-delay:{p.delay}s, {p.shimmerDelay}s;
             animation-duration:{p.duration}s, {p.shimmerDuration}s;"
    />
  {/each}
</div>

<style>
  .dev-unlock-celebration {
    position: fixed; inset: 0; pointer-events: none; overflow: hidden; z-index: 300;
  }
  .dev-mode-text {
    position: absolute; top: 50%; left: 50%;
    transform: translate(-50%, -50%) scale(0);
    font-size: 2.5rem; font-weight: 800; letter-spacing: 0.05em;
    color: var(--accent); text-shadow: 0 2px 12px rgba(0, 0, 0, 0.5);
    animation: dev-mode-pop 0.5s cubic-bezier(0.34, 1.56, 0.64, 1) forwards;
    white-space: nowrap;
  }
  @keyframes dev-mode-pop {
    0%   { transform: translate(-50%, -50%) scale(0); opacity: 0; }
    60%  { transform: translate(-50%, -50%) scale(1.15); opacity: 1; }
    100% { transform: translate(-50%, -50%) scale(1); opacity: 1; }
  }
  .piece {
    position: absolute;
    top: -40px;
    opacity: 0.95;
    /* Two independent animations on two different properties (transform
       vs. filter), so the fall and the shimmer never fight each other. */
    animation-name: dickbutt-fall, dickbutt-shimmer;
    animation-timing-function: ease-in, ease-in-out;
    animation-fill-mode: forwards, none;
    animation-iteration-count: 1, infinite;
  }
  @keyframes dickbutt-fall {
    0%   { transform: translateY(0) rotate(0deg); opacity: 0.95; }
    100% { transform: translateY(110vh) rotate(var(--rot)); opacity: 0; }
  }
  @keyframes dickbutt-shimmer {
    /* drop-shadow (not box-shadow) hugs the PNG's actual alpha-masked
       silhouette — the glow traces the drawing's lines, not a box around
       the image's transparent margins. */
    0%, 100% { filter: drop-shadow(0 0 2px gold); }
    50%      { filter: drop-shadow(0 0 8px gold); }
  }
</style>
