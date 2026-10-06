<script>
  import { t } from '../../lib/i18n.js';
  // A player's profile: the achievements with their badges, in sections by game mode, each
  // split into earned and still to earn. Secret ones that are not earned yet come last.
  import { cap } from '../../lib/util.js';
  import { localized, isEarned, groupAchievements, progressText, rarityText } from '../../lib/achievements.js';
  import Badge from '../../lib/components/Badge.svelte';
  import PageHeader from '../../lib/components/PageHeader.svelte';
  import Panel from '../../lib/components/Panel.svelte';
  import Avatar from '../../lib/components/Avatar.svelte';
  import { players } from '../../lib/stores/players.js';
  import { apiJson } from '../../lib/api.js';

  let { name } = $props();

  let sections = $state([]);
  let total = $state(0);
  let earnedTotal = $state(0);
  let status = $state('loading');   // loading | ready | error

  $effect(() => {
    const player = name;
    status = 'loading';
    fetch(`/api/achievements/${encodeURIComponent(player)}`)
      .then((r) => r.json())
      .then((body) => {
        if (player !== name) return;
        const items = body.achievements || [];
        sections = groupAchievements(items);
        total = items.length;
        earnedTotal = items.filter(isEarned).length;
        status = 'ready';
      })
      .catch(() => { if (player === name) status = 'error'; });
  });

  // The player's color, used to draw their darts in games that show several players on one
  // board. Saved as soon as it is picked; clearing it leaves the player without a color.
  let color = $derived($players.colorFor(name));
  let colorError = $state('');

  async function saveColor(value) {
    colorError = '';
    const res = await apiJson('PATCH', `/api/players/${encodeURIComponent(name)}/color`, { color: value });
    if (res.error) colorError = t(res.error);
  }

  function earnedLine(item) {
    const date = new Date(item.earned_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
    return item.tiers ? t('Earned {date} · tier {tier} of {count}', { date, tier: item.tier, count: item.tiers.length }) : t('Earned {date}', { date });
  }
</script>

<PageHeader title={cap(name)} back="#players">
  {#snippet lead()}<Avatar {name} {color} size={64} />{/snippet}
</PageHeader>

<Panel>
  <div class="color-row">
    <label for="playerColor">{t('Color')}</label>
    <input type="color" id="playerColor" value={color || '#7c6aff'}
           onchange={(e) => saveColor(e.currentTarget.value)}>
    <span class="color-hint">
      {#if color}{color}{:else}{t('No color set, a random one is picked when a game needs it.')}{/if}
    </span>
    {#if color}
      <button type="button" class="clear" onclick={() => saveColor(null)}>{t('Clear')}</button>
    {/if}
    {#if colorError}<span class="color-error">{colorError}</span>{/if}
  </div>
</Panel>

{#if status === 'loading'}
  <p class="note">{t('Loading…')}</p>
{:else if status === 'error'}
  <p class="note">{t('The achievements could not be loaded.')}</p>
{:else if !total}
  <p class="note">{t('Achievements are not available without the stats database.')}</p>
{:else}
  <div class="summary">
    <span>{t('Achievements · {earned} of {total}', { earned: earnedTotal, total })}</span>
    <span class="bar"><span class="fill" style="width: {(100 * earnedTotal / total).toFixed(1)}%"></span></span>
  </div>
  {#each sections as section (section.key)}
    <Panel>
      <div class="title">
        <span>{section.label}</span>
        {#if section.key !== 'secret'}<span class="count">{t('{n} of {total}', { n: section.earned.length, total: section.total })}</span>{/if}
      </div>
      {#each [[t('Earned'), section.earned], [t('To earn'), section.open]] as [heading, list]}
        {#if list.length}
          {#if section.key !== 'secret'}<div class="sub">{heading}</div>{/if}
          <ul class="grid">
            {#each list as item (item.id)}
              <li class="card" class:earned={isEarned(item)}>
                <Badge {item} size={72} />
                <div class="text">
                  <div class="name">{localized(item.names) || t('Secret achievement')}</div>
                  <div class="desc">{localized(item.descriptions) || t('Keep playing to find out.')}</div>
                  {#if isEarned(item)}
                    <div class="meta">{earnedLine(item)}</div>
                  {/if}
                  {#if progressText(item)}
                    <div class="meta">{progressText(item)}</div>
                  {/if}
                  {#if rarityText(item)}
                    <div class="rarity">{rarityText(item)}</div>
                  {/if}
                </div>
              </li>
            {/each}
          </ul>
        {/if}
      {/each}
    </Panel>
  {/each}
{/if}

<style>
  .note { color: var(--muted); font-size: 0.95rem; }
  .color-row { display: flex; align-items: center; gap: 0.9rem; flex-wrap: wrap; }
  .color-row label { font-size: 0.8rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); }
  .color-row input[type='color'] {
    width: 2.6rem; height: 2.6rem; padding: 0; border: 1px solid var(--glass-border); border-radius: 50%;
    background: none; cursor: pointer; overflow: hidden;
  }
  .color-row input[type='color']::-webkit-color-swatch-wrapper { padding: 0; }
  .color-row input[type='color']::-webkit-color-swatch { border: none; border-radius: 50%; }
  .color-hint { font-size: 0.95rem; color: color-mix(in srgb, var(--text) 72%, transparent); }
  .clear {
    font-size: 0.85rem; background: var(--glass); border: 1px solid var(--glass-border); border-radius: 999px;
    color: var(--muted); padding: 0.3rem 0.9rem; cursor: pointer; font-family: inherit;
    transition: border-color 0.15s, color 0.15s;
  }
  .clear:hover { border-color: var(--accent); color: var(--accent); }
  .color-error { font-size: 0.85rem; color: var(--red); }
  .summary {
    display: flex; align-items: center; gap: 1rem; margin: 0.5rem 0 1rem;
    font-size: 0.8rem; color: var(--muted); font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
  }
  .bar { flex: 1; height: 6px; border-radius: 999px; background: rgba(255, 255, 255, 0.1); overflow: hidden; max-width: 22rem; }
  .fill { display: block; height: 100%; border-radius: 999px; background: var(--accent); box-shadow: 0 0 10px var(--accent); }
  .title {
    display: flex; justify-content: space-between; align-items: baseline;
    font-size: 1.25rem; font-weight: 800; letter-spacing: -0.01em; margin-bottom: 1rem;
  }
  .count { font-size: 0.85rem; font-weight: 600; color: var(--muted); }
  .sub {
    font-size: 0.72rem; color: var(--muted); font-weight: 700; letter-spacing: 0.08em;
    text-transform: uppercase; margin: 0.25rem 0 0.6rem;
  }
  .grid {
    list-style: none; padding: 0;
    display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 0.85rem;
    margin-bottom: 1.1rem;
  }
  .grid:last-child { margin-bottom: 0; }
  .card {
    display: flex; align-items: center; gap: 1rem; padding: 0.85rem;
    background: rgba(0, 0, 0, 0.22); border: 1px solid var(--glass-border); border-radius: 14px;
    transition: border-color 0.2s, background 0.2s;
  }
  .card.earned {
    border-color: color-mix(in srgb, var(--accent) 55%, transparent);
    background: color-mix(in srgb, var(--accent) 9%, rgba(0, 0, 0, 0.2));
    box-shadow: 0 0 22px -10px var(--accent);
  }
  .text { min-width: 0; }
  .name { font-weight: 700; font-size: 1rem; }
  .card:not(.earned) .name { color: color-mix(in srgb, var(--text) 70%, transparent); }
  .desc { font-size: 0.85rem; color: color-mix(in srgb, var(--text) 62%, transparent); margin-top: 0.2rem; }
  .meta { font-size: 0.8rem; color: var(--accent); margin-top: 0.3rem; }
  .rarity { font-size: 0.8rem; color: var(--muted); margin-top: 0.3rem; }
</style>
