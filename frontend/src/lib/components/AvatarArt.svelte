<script>
  // The picture of an avatar without its frame: the shapes of a little dartboard, drawn in a
  // coordinate system from -50 to 50 so a parent <svg viewBox="-50 -50 100 100"> can show it.
  // Shared by Avatar.svelte and the dart markers of the board (see lib/avatar.js).
  import { avatarSpec } from '../avatar.js';
  import { bandPath } from '../dartboard.js';

  let { name, color = null } = $props();

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
