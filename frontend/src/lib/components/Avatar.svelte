<script>
  // A player's avatar: a little dartboard that is the same for the same name every time, drawn in
  // the hue of the player's color when one is set (see lib/avatar.js).
  import AvatarArt from './AvatarArt.svelte';

  let { name, color = null, size = 40 } = $props();
</script>

<svg width={size} height={size} viewBox="-50 -50 100 100" role="img" aria-label="Avatar of {name}">
  <AvatarArt {name} {color} />
</svg>

<style>
  svg { display: block; border-radius: 50%; flex-shrink: 0; }
</style>
