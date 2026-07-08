<script>
  // passes = score > target, so target itself isn't enough to beat it —
  // show the actual minimum passing score (target + 1), same reasoning
  // as the filler_target audio cue.
  let { target = 0 } = $props();
</script>

<div class="live-target">
  <div class="label">Target</div>
  <div class="value">{target + 1}</div>
</div>

<style>
  .live-target { text-align: right; }
  .live-target .label { font-size: 0.75rem; color: var(--muted); }
  .live-target .value { font-size: 2rem; font-weight: 800; color: var(--yellow); }
</style>
