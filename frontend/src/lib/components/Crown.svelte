<script>
  import { t } from '../i18n.js';
  // The mockup's crown — mockups/elimination_crown_mockups.png +
  // mockups/crown.png — shown above/overlapping the first letter of
  // whoever currently has the most Elimination wins, so it reads as
  // "wearing" the crown rather than a floating icon. Must be placed
  // inside a `position: relative; display: inline-block;` wrapper
  // around the name text (see EliminationTv.svelte's .name-crown-wrap).
  import crownUrl from '../assets/crown.png';
</script>

<img class="crown-icon" src={crownUrl} alt={t('Most elimination wins')} />

<style>
  .crown-icon {
    position: absolute;
    z-index: 1;
    top: -0.60em;
    left: -0.60em;
    width: 1.3em;
    height: auto;
    pointer-events: none;
    filter: drop-shadow(0 2px 5px rgba(0, 0, 0, 0.55));
  }
</style>
