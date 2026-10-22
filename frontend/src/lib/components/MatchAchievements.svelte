<script>
  import { t } from '../i18n.js';
  // The achievements earned in a finished match, grouped by player: the badge, the name and the tier; a click
  // opens the description. It shows nothing for a match without any (and for one that was not finished). It is
  // used on the result pages of the games and in the match list of the Stats page.
  import { shownName } from '../util.js';
  import { localized } from '../achievements.js';
  import Badge from './Badge.svelte';

  let { matchId, large = false } = $props();

  let items = $state([]);
  let open = $state(null);

  async function load(id) {
    open = null;
    if (!id) { items = []; return; }
    try {
      const body = await fetch(`/api/stats/match/${encodeURIComponent(id)}/achievements`).then((r) => r.json());
      if (id === matchId) items = body.achievements || [];
    } catch (e) {
      if (id === matchId) items = [];
    }
  }

  $effect(() => { load(matchId); });

  let groups = $derived.by(() => {
    const byPlayer = new Map();
    for (const item of items) {
      if (!byPlayer.has(item.player)) byPlayer.set(item.player, []);
      byPlayer.get(item.player).push(item);
    }
    return [...byPlayer].map(([player, list]) => ({ player, list }));
  });

  const keyOf = (item) => `${item.player}/${item.id}/${item.tier}`;
  const tierText = (item) => (item.tiers ? t('tier {tier} of {count}', { tier: item.tier, count: item.tiers.length }) : '');
  let openItem = $derived(items.find((i) => keyOf(i) === open) || null);
</script>

{#if items.length}
  <div class="earned" class:large>
    <div class="title">{t('Achievements earned')}</div>
    <div class="groups">
    {#each groups as group (group.player)}
      <div class="group">
        <span class="who">{shownName(group.player)}</span>
        <div class="items">
          {#each group.list as item (keyOf(item))}
            <button type="button" class="item" class:open={open === keyOf(item)} aria-expanded={open === keyOf(item)}
                    onclick={(e) => { e.stopPropagation(); open = open === keyOf(item) ? null : keyOf(item); }}>
              <Badge {item} size={large ? 56 : 52} />
              <span class="text">
                <span class="name">{localized(item.names)}</span>
                {#if tierText(item)}<span class="tier">{tierText(item)}</span>{/if}
              </span>
            </button>
          {/each}
        </div>
      </div>
    {/each}
    </div>
    {#if openItem}
      <div class="desc" role="status">{localized(openItem.descriptions)}</div>
    {/if}
  </div>
{/if}

<style>
  .earned { display: flex; flex-direction: column; gap: 0.6rem; margin-top: 1.25rem; }
  .title { font-size: 0.75rem; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; color: var(--accent); }
  .groups { display: flex; flex-wrap: wrap; gap: 0.8rem 2rem; }
  .group { display: flex; flex-direction: column; gap: 0.35rem; }
  .who { font-size: 0.85rem; font-weight: 700; color: var(--muted); }
  .items { display: flex; flex-wrap: wrap; gap: 0.5rem; }
  .item {
    display: flex; align-items: center; gap: 0.6rem; max-width: 100%; text-align: left; font-family: inherit; color: inherit; cursor: pointer;
    padding: 0.35rem 0.9rem 0.35rem 0.4rem; border-radius: 999px;
    background: var(--glass); border: 1px solid var(--glass-border);
  }
  .item:hover, .item.open { border-color: var(--accent); }
  .text { display: flex; flex-direction: column; min-width: 0; }
  .name { font-weight: 700; line-height: 1.2; }
  .tier { font-size: 0.75rem; color: var(--muted); }
  .desc { font-size: 0.9rem; color: color-mix(in srgb, var(--text) 85%, transparent); padding: 0.5rem 0.9rem; border-left: 3px solid var(--accent); }
  .large { gap: clamp(0.4rem, 0.8vw, 0.8rem); margin-top: 0; align-items: center; max-height: 26vh; overflow-y: auto; }
  .large .groups { justify-content: center; }
  .large .title { font-size: clamp(0.8rem, 1.2vw, 1.1rem); }
  .large .group { flex-direction: row; align-items: center; gap: 0.7rem; }
  .large .items { justify-content: center; }
  .large .who { font-size: clamp(0.9rem, 1.4vw, 1.3rem); }
  .large .name { font-size: clamp(1rem, 1.6vw, 1.5rem); }
  .large .tier { font-size: clamp(0.8rem, 1.1vw, 1.05rem); }
  .large .desc { font-size: clamp(0.95rem, 1.4vw, 1.3rem); max-width: 60rem; text-align: center; }
</style>
