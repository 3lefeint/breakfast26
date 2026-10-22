<script>
  import { t } from '../../lib/i18n.js';
  // The unlock banner, like a console achievement: it slides in at the top, stays a few
  // seconds and slides out again. Several earned at once are shown one after the other.
  import { achievementQueue, achievementShown } from '../../lib/stores/achievementQueue.js';
  import { shownName } from '../../lib/util.js';
  import { localized } from '../../lib/achievements.js';
  import Badge from '../../lib/components/Badge.svelte';

  let current = $derived($achievementQueue[0]);

  function byline(item) {
    return item.tiers ? `${shownName(item.player)} · ${t('tier {tier} of {count}', { tier: item.tier, count: item.tiers.length })}` : shownName(item.player);
  }
</script>

{#if current}
  {#key current}
    <div class="banner" role="status" aria-live="polite" onanimationend={achievementShown}>
      <Badge item={current} size={96} />
      <div class="text">
        <div class="kicker">{t('Achievement unlocked')}</div>
        <div class="name">{localized(current.names)}</div>
        <div class="who">{byline(current)}</div>
      </div>
    </div>
  {/key}
{/if}

<style>
  .banner {
    position: fixed; top: 0.75rem; left: 50%; z-index: 100;
    display: flex; align-items: center; gap: 1.5rem;
    min-width: 33rem; max-width: calc(100vw - 2rem);
    padding: 1rem 2.1rem 1rem 1.3rem;
    background: var(--surface); border: 1px solid var(--accent); border-radius: 999px;
    box-shadow: 0 8px 30px rgba(0, 0, 0, 0.5), 0 0 24px color-mix(in srgb, var(--accent) 35%, transparent);
    transform: translate(-50%, -160%);
    animation: unlock 5.2s ease-in-out forwards;
  }
  .kicker { font-size: 1.05rem; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; color: var(--accent); }
  .name { font-size: 1.95rem; font-weight: 800; line-height: 1.2; }
  .who { font-size: 1.3rem; color: var(--muted); }

  @keyframes unlock {
    0%   { transform: translate(-50%, -160%); }
    8%   { transform: translate(-50%, 0); }
    92%  { transform: translate(-50%, 0); }
    100% { transform: translate(-50%, -160%); }
  }
  @media (prefers-reduced-motion: reduce) {
    .banner { transform: translate(-50%, 0); opacity: 0; animation-name: unlock-fade; }
    @keyframes unlock-fade { 0% { opacity: 0; } 8%, 92% { opacity: 1; } 100% { opacity: 0; } }
  }
</style>
