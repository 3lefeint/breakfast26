<script>
  // The background of the interface: a deep base color with three large soft color areas that drift
  // slowly, and a few tilted streaks. The colors come from the --aurora-* tokens of the accent preset. It stands still
  // when the system asks for reduced motion.
</script>

<div class="aurora" aria-hidden="true">
  <span class="blob a"></span>
  <span class="blob b"></span>
  <span class="blob c"></span>
  <span class="streak s1"></span>
  <span class="streak s2"></span>
  <span class="streak s3"></span>
</div>

<style>
  .aurora {
    position: fixed; inset: 0; z-index: -1; overflow: hidden; pointer-events: none;
    background: var(--aurora-base);
  }
  .blob {
    position: absolute; border-radius: 50%; will-change: transform;
    width: 75vmax; height: 75vmax; opacity: 0.85;
    filter: blur(60px);
  }
  .a { background: radial-gradient(circle, var(--aurora-1) 0%, transparent 68%); left: -22vmax; top: -22vmax; animation: drift-a 15s ease-in-out infinite alternate; }
  .b { background: radial-gradient(circle, var(--aurora-2) 0%, transparent 68%); right: -25vmax; top: 0; animation: drift-b 19s ease-in-out infinite alternate; }
  .c { background: radial-gradient(circle, var(--aurora-3) 0%, transparent 68%); left: 8vmax; bottom: -38vmax; animation: drift-c 21s ease-in-out infinite alternate; }

  /* Long soft streaks across the picture, tilted like the bands of an aurora. */
  .streak {
    position: absolute; width: 120vmax; height: 16vmax; border-radius: 50%;
    filter: blur(38px); will-change: transform; opacity: 0.8;
  }
  .s1 { background: linear-gradient(90deg, transparent, var(--aurora-2) 35%, var(--aurora-1) 65%, transparent); left: -30vmax; top: 38%; transform: rotate(-32deg); animation: streak-1 12s ease-in-out infinite alternate; }
  .s2 { background: linear-gradient(90deg, transparent, var(--aurora-1) 40%, var(--aurora-3) 70%, transparent); left: -10vmax; top: 8%; height: 11vmax; transform: rotate(-28deg); animation: streak-2 15s ease-in-out infinite alternate; }
  .s3 { background: linear-gradient(90deg, transparent, var(--aurora-3) 30%, var(--aurora-2) 60%, transparent); left: -25vmax; top: 72%; height: 13vmax; transform: rotate(-36deg); animation: streak-3 17s ease-in-out infinite alternate; }

  @keyframes drift-a { from { transform: translate(-8vmax, -6vmax) scale(0.95); } to { transform: translate(42vmax, 34vmax) scale(1.35); } }
  @keyframes drift-b { from { transform: translate(8vmax, -4vmax) scale(1.25); } to { transform: translate(-42vmax, 38vmax) scale(0.85); } }
  @keyframes drift-c { from { transform: translate(-6vmax, 6vmax) scale(0.9); } to { transform: translate(48vmax, -30vmax) scale(1.4); } }
  @keyframes streak-1 { from { transform: translate(-16vmax, 12vmax) rotate(-42deg); } to { transform: translate(30vmax, -22vmax) rotate(-18deg); } }
  @keyframes streak-2 { from { transform: translate(20vmax, -10vmax) rotate(-20deg); } to { transform: translate(-26vmax, 24vmax) rotate(-44deg); } }
  @keyframes streak-3 { from { transform: translate(-14vmax, 16vmax) rotate(-46deg); } to { transform: translate(34vmax, -18vmax) rotate(-20deg); } }

  @media (prefers-reduced-motion: reduce) {
    .blob, .streak { animation: none; }
  }
</style>
