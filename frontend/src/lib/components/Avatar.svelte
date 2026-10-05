<script>
  // A player's avatar: a little dartboard that is the same for the same name every time, drawn in
  // the hue of the player's color when one is set (see lib/avatar.js).
  import { avatarSpec } from '../avatar.js';
  import { bandPath } from '../dartboard.js';

  let { name, color = null, size = 40 } = $props();

  // The board in a drawing 100 wide: the radius of the double ring is 50.
  const S = 0.5;
  const R = { bull: 8, outerBull: 15, singleIn: 15, tripleIn: 58, tripleOut: 70, doubleIn: 88, doubleOut: 100 };

  let spec = $derived(avatarSpec(name, color));
  let shapes = $derived(spec.segments.map((seg, i) => {
    const a0 = i * 18 - 9 + spec.rotation, a1 = i * 18 + 9 + spec.rotation;
    return {
      inner: bandPath(R.singleIn, R.tripleIn, a0, a1, S),
      triple: bandPath(R.tripleIn, R.tripleOut, a0, a1, S),
      outer: bandPath(R.tripleOut, R.doubleIn, a0, a1, S),
      double: bandPath(R.doubleIn, R.doubleOut, a0, a1, S),
      ...seg,
    };
  }));
</script>

<svg width={size} height={size} viewBox="-50 -50 100 100" role="img" aria-label="Avatar of {name}">
  <circle r="50" fill="#0b1020" />
  {#each shapes as s}
    <path d={s.inner} fill={s.fill} />
    <path d={s.outer} fill={s.fill} />
    <path d={s.triple} fill={s.lit ? s.fill : s.ring} />
    <path d={s.double} fill={s.lit ? s.fill : s.ring} />
  {/each}
  <circle r={R.outerBull * S} fill={spec.outerBull} />
  <circle r={R.bull * S} fill={spec.bull} />
  <circle r="49" fill="none" stroke={spec.edge} stroke-width="2" opacity="0.8" />
</svg>

<style>
  svg { display: block; border-radius: 50%; flex-shrink: 0; }
</style>
