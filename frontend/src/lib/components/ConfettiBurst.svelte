<script>
  // A small win-confetti burst, fired once when this
  // component mounts (put it on the Elimination finished screen). Pure
  // CSS keyframe animation, no library — matches the app's no-CDN style.
  const COLORS = ['var(--accent)', 'var(--green)', 'var(--yellow)', 'var(--red)'];
  const COUNT = 40;

  const pieces = Array.from({ length: COUNT }, (_, i) => ({
    id: i,
    left: Math.random() * 100,
    delay: Math.random() * 0.3,
    duration: 1.6 + Math.random() * 0.8,
    rotate: Math.random() * 360,
    color: COLORS[i % COLORS.length],
  }));
</script>

<div class="confetti-burst" aria-hidden="true">
  {#each pieces as p (p.id)}
    <span
      class="piece"
      style="left:{p.left}%; background:{p.color}; animation-delay:{p.delay}s; animation-duration:{p.duration}s; --rot:{p.rotate}deg"
    ></span>
  {/each}
</div>

<style>
  .confetti-burst {
    position: fixed; inset: 0; pointer-events: none; overflow: hidden; z-index: 200;
  }
  .piece {
    position: absolute;
    top: -10px;
    width: 8px; height: 14px;
    opacity: 0.9;
    animation-name: confetti-fall;
    animation-timing-function: ease-in;
    animation-fill-mode: forwards;
  }
  @keyframes confetti-fall {
    0%   { transform: translateY(0) rotate(0deg); opacity: 0.9; }
    100% { transform: translateY(100vh) rotate(var(--rot)); opacity: 0; }
  }
</style>
