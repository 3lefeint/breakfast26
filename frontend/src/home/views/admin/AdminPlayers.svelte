<script>
  import { t } from '../../../lib/i18n.js';
  // The players of the circle, and per approved site which of its players is which circle player (the player of the same name is
  // only suggested: a click confirms it).
  import Panel from '../../../lib/components/Panel.svelte';
  import { confirmDialog } from '../../../lib/confirm.js';
  import { shownName } from '../../../lib/util.js';

  let { sites, approved, players, act } = $props();
  let name = $state('');

  async function add() {
    const text = name.trim();
    if (!text) return;
    if (await act('POST', '/admin/players', { name: text })) name = '';
  }

  async function remove(player) {
    if (!await confirmDialog(t('Delete {name} from the circle? Mappings and rules of the player go, the records stay.', { name: player.name }))) return;
    await act('DELETE', `/admin/players/${player.id}`);
  }

  const mappedTo = (site, local) => players.find((p) => p.mappings.some((m) => m.location_id === site.id && m.local_name === local))?.id || '';
  const suggestion = (local) => players.find((p) => p.name.toLowerCase() === local);
  const setMapping = (site, local, playerId) => act('PUT', '/admin/mappings', { location_id: site.id, local_name: local, player_id: playerId || null });

  // The names to map at a site: those it reported and those already mapped.
  function names(site) {
    const mapped = players.flatMap((p) => p.mappings.filter((m) => m.location_id === site.id).map((m) => m.local_name));
    return [...new Set([...site.players, ...mapped])].sort();
  }
</script>

<Panel title={t('Players of the circle')}>
  <div class="row wide"><input type="text" maxlength="40" placeholder={t('Name')} aria-label={t('Name')} bind:value={name} onkeydown={(e) => e.key === 'Enter' && add()}><button type="button" class="btn primary" disabled={!name.trim()} onclick={add}>{t('Add')}</button></div>
  {#if !players.length}
    <p class="empty">{t('No player yet.')}</p>
  {:else}
    <table>
      <tbody>
        {#each players as player (player.id)}
          <tr><td><strong>{player.name}</strong></td><td class="num"><button type="button" class="btn small" onclick={() => remove(player)}>{t('Delete')}</button></td></tr>
        {/each}
      </tbody>
    </table>
  {/if}
</Panel>

{#each approved as site (site.id)}
  <Panel title={t('Players of {site}', { site: site.name })}>
    {#if !names(site).length}
      <p class="empty">{t('This site has not reported any player yet.')}</p>
    {:else}
      <table>
        <thead><tr><th>{t('Player at the site')}</th><th>{t('Is the circle player')}</th></tr></thead>
        <tbody>
          {#each names(site) as local (local)}
            {@const current = mappedTo(site, local)}
            {@const same = suggestion(local)}
            <tr>
              <td>{shownName(local)}</td>
              <td>
                <select value={current} aria-label={t('Circle player of {name}', { name: shownName(local) })} onchange={(e) => setMapping(site, local, e.currentTarget.value)}>
                  <option value="">—</option>
                  {#each players as p (p.id)}<option value={p.id}>{p.name}</option>{/each}
                </select>
                {#if !current && same}
                  <button type="button" class="btn small" onclick={() => setMapping(site, local, same.id)}>{t('Same name: {name}', { name: same.name })}</button>
                {/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </Panel>
{:else}
  {#if sites.length}<p class="empty">{t('Approve a site first, then its players can be mapped here.')}</p>{/if}
{/each}
