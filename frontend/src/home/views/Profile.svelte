<script>
  // A player's profile: the achievements with their badges, in sections by game mode, each
  // split into earned and still to earn. Secret ones that are not earned yet come last.
  import { cap } from '../../lib/util.js';
  import { localized, isEarned, groupAchievements, progressText, rarityText } from '../../lib/achievements.js';
  import Badge from '../../lib/components/Badge.svelte';
  import PageHeader from '../../lib/components/PageHeader.svelte';
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
    if (res.error) colorError = res.error;
  }

  function earnedLine(item) {
    const date = new Date(item.earned_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
    return item.tiers ? `Earned ${date} · tier ${item.tier} of ${item.tiers.length}` : `Earned ${date}`;
  }
</script>

<PageHeader title={cap(name)} back="#players" />

<div class="color-row">
  <label for="playerColor">Color</label>
  <input type="color" id="playerColor" value={color || '#7c6aff'}
         onchange={(e) => saveColor(e.currentTarget.value)}>
  <span class="color-hint">
    {#if color}{color}{:else}No color set, a random one is picked when a game needs it.{/if}
  </span>
  {#if color}
    <button type="button" class="clear" onclick={() => saveColor(null)}>Clear</button>
  {/if}
  {#if colorError}<span class="color-error">{colorError}</span>{/if}
</div>

{#if status === 'loading'}
  <p class="note">Loading…</p>
{:else if status === 'error'}
  <p class="note">The achievements could not be loaded.</p>
{:else if !total}
  <p class="note">Achievements are not available without the stats database.</p>
{:else}
  <div class="summary">Achievements · {earnedTotal} of {total}</div>
  {#each sections as section (section.key)}
    <div class="section">
      <div class="title">
        <span>{section.label}</span>
        {#if section.key !== 'secret'}<span class="count">{section.earned.length} of {section.total}</span>{/if}
      </div>
      {#each [['Earned', section.earned], ['To earn', section.open]] as [heading, list]}
        {#if list.length}
          {#if section.key !== 'secret'}<div class="sub">{heading}</div>{/if}
          <ul class="grid">
            {#each list as item (item.id)}
              <li class="card" class:earned={isEarned(item)}>
                <Badge {item} size={72} />
                <div class="text">
                  <div class="name">{localized(item.names) || 'Secret achievement'}</div>
                  <div class="desc">{localized(item.descriptions) || 'Keep playing to find out.'}</div>
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
    </div>
  {/each}
{/if}

<style>
  .note { color: var(--muted); font-size: 0.9rem; }
  .color-row {
    display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap;
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 0.9rem 1.25rem; margin-bottom: 1rem;
  }
  .color-row label { font-size: 0.8rem; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); }
  .color-row input[type='color'] { width: 2.5rem; height: 2rem; padding: 0; border: 1px solid var(--border); border-radius: 6px; background: none; cursor: pointer; }
  .color-hint { font-size: 0.85rem; color: var(--muted); }
  .clear { font-size: 0.8rem; background: none; border: 1px solid var(--border); border-radius: 6px; color: var(--text); padding: 0.2rem 0.6rem; cursor: pointer; }
  .clear:hover { border-color: var(--accent); color: var(--accent); }
  .color-error { font-size: 0.8rem; color: var(--red); }
  .summary {
    font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em;
    text-transform: uppercase; margin-bottom: 0.75rem;
  }
  .section {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 1.25rem; margin-bottom: 1rem;
  }
  .title {
    display: flex; justify-content: space-between; align-items: baseline;
    font-size: 1rem; font-weight: 800; margin-bottom: 0.9rem;
  }
  .count { font-size: 0.8rem; font-weight: 600; color: var(--muted); }
  .sub {
    font-size: 0.7rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em;
    text-transform: uppercase; margin: 0.25rem 0 0.5rem;
  }
  .grid {
    list-style: none; padding: 0;
    display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 0.75rem;
    margin-bottom: 1rem;
  }
  .section > .grid:last-child { margin-bottom: 0; }
  .card {
    display: flex; align-items: center; gap: 0.9rem; padding: 0.75rem;
    background: var(--bg); border: 1px solid var(--border); border-radius: 10px;
  }
  .card.earned { border-color: color-mix(in srgb, var(--accent) 45%, var(--border)); }
  .text { min-width: 0; }
  .name { font-weight: 700; font-size: 0.95rem; }
  .card:not(.earned) .name { color: var(--muted); }
  .desc { font-size: 0.8rem; color: var(--muted); margin-top: 0.15rem; }
  .meta { font-size: 0.75rem; color: var(--accent); margin-top: 0.25rem; }
  .rarity { font-size: 0.75rem; color: var(--muted); margin-top: 0.25rem; }
</style>
