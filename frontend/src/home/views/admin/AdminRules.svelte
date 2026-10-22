<script>
  import { t } from '../../../lib/i18n.js';
  // The rules: a table of the circle players and the approved sites. A tick means that the matches of the player go to that site,
  // wherever they were played.
  import Panel from '../../../lib/components/Panel.svelte';

  let { approved, players, act } = $props();

  async function toggle(player, site, on) {
    const ids = new Set(player.sites);
    if (on) ids.add(site.id); else ids.delete(site.id);
    await act('PUT', '/admin/rules', { player_id: player.id, location_ids: [...ids] });
  }
</script>

<Panel title={t('Rules')}>
  <p class="note">{t('Every finished match goes to the sites ticked for a player who took part in it, wherever it was played. The site where it was played keeps it anyway.')}</p>
  {#if !players.length || !approved.length}
    <p class="empty">{t('Rules need a player of the circle and an approved site.')}</p>
  {:else}
    <table>
      <thead><tr><th>{t('Player')}</th>{#each approved as site (site.id)}<th class="num">{site.name}</th>{/each}</tr></thead>
      <tbody>
        {#each players as player (player.id)}
          <tr>
            <td><strong>{player.name}</strong></td>
            {#each approved as site (site.id)}
              <td class="num"><input type="checkbox" checked={player.sites.includes(site.id)} aria-label={`${player.name} → ${site.name}`}
                                     onchange={(e) => toggle(player, site, e.currentTarget.checked)}></td>
            {/each}
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</Panel>
