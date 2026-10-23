<script>
  import { t } from '../../../lib/i18n.js';
  // The players of the circle, as one table: a row per circle player, a column per approved site. A cell says whether the site
  // gets the matches of the player (the tick, the rule) and who he is at that site (the select, the mapping). Choosing a name
  // ticks the cell; a tick without a name is allowed, the site then stores the player as a guest. Below the table: the players
  // the sites reported that no circle player stands for yet.
  import Panel from '../../../lib/components/Panel.svelte';
  import { confirmDialog } from '../../../lib/confirm.js';
  import { shownName } from '../../../lib/util.js';

  let { approved, players, actAll } = $props();
  let name = $state('');

  async function add() {
    const text = name.trim();
    if (!text) return;
    if (await actAll([['POST', '/admin/players', { name: text }]])) name = '';
  }

  async function remove(player) {
    if (!await confirmDialog(t('Delete {name} from the circle? Mappings and rules of the player go, the records stay.', { name: player.name }))) return;
    await actAll([['DELETE', `/admin/players/${player.id}`]]);
  }

  const namesOf = (player, site) => player.mappings.filter((m) => m.location_id === site.id).map((m) => m.local_name);
  const ticked = (player, site) => player.sites.includes(site.id);
  const taken = (site) => new Map(players.flatMap((p) => p.mappings.filter((m) => m.location_id === site.id).map((m) => [m.local_name, p.id])));

  // What a cell can choose: the names the site reported and those mapped here already, not those that stand for another player.
  function options(player, site) {
    const owner = taken(site);
    return [...new Set([...site.players, ...owner.keys()])].filter((n) => !owner.has(n) || owner.get(n) === player.id).sort();
  }

  // The names of the site that no circle player stands for.
  const unmapped = (site) => { const owner = taken(site); return site.players.filter((n) => !owner.has(n)).sort(); };

  const unmap = (player, site, keep) => namesOf(player, site).filter((n) => n !== keep)
    .map((n) => ['PUT', '/admin/mappings', { location_id: site.id, local_name: n, player_id: null }]);
  const rule = (player, site, on) => ['PUT', '/admin/rules', {
    player_id: player.id, location_ids: [...new Set(on ? [...player.sites, site.id] : player.sites.filter((id) => id !== site.id))] }];

  // The tick: the site gets the matches of the player or not.
  const tick = (player, site, on) => actAll([rule(player, site, on)]);

  // The select: who the player is at the site. A name ticks the cell, "not there" leaves the tick as it is.
  function choose(player, site, local) {
    const calls = unmap(player, site, local || null);
    if (local) {
      calls.push(['PUT', '/admin/mappings', { location_id: site.id, local_name: local, player_id: player.id }]);
      if (!ticked(player, site)) calls.push(rule(player, site, true));
    }
    return actAll(calls);
  }

  const sameName = (name) => players.find((p) => p.name.toLowerCase() === name);
</script>

<Panel title={t('Players of the circle')}>
  <div class="row wide"><input type="text" maxlength="40" placeholder={t('Name')} aria-label={t('Name')} bind:value={name} onkeydown={(e) => e.key === 'Enter' && add()}><button type="button" class="btn primary" disabled={!name.trim()} onclick={add}>{t('Add')}</button></div>
  <p class="note">{t('Tick a site to send it the matches of a player, wherever they were played. Choose who the player is at that site: the matches then count for him there, otherwise he is a guest. The site where a match was played keeps it anyway.')}</p>
  {#if !players.length}
    <p class="empty">{t('No player yet.')}</p>
  {:else if !approved.length}
    <p class="empty">{t('Approve a site first, then its players can be mapped here.')}</p>
  {:else}
    <div class="scroll">
      <table>
        <thead><tr><th>{t('Player')}</th>{#each approved as site (site.id)}<th>{site.name}</th>{/each}<th></th></tr></thead>
        <tbody>
          {#each players as player (player.id)}
            <tr>
              <td><strong>{player.name}</strong></td>
              {#each approved as site (site.id)}
                <td class="cell">
                  <input type="checkbox" checked={ticked(player, site)} aria-label={`${player.name} → ${site.name}`} onchange={(e) => tick(player, site, e.currentTarget.checked)}>
                  <select class="pick" value={namesOf(player, site)[0] || ''} aria-label={t('Circle player of {name}', { name: `${player.name} · ${site.name}` })} onchange={(e) => choose(player, site, e.currentTarget.value)}>
                    <option value="">{t('not there')}</option>
                    {#each options(player, site) as n (n)}<option value={n}>{shownName(n)}</option>{/each}
                  </select>
                </td>
              {/each}
              <td class="num"><button type="button" class="btn small" onclick={() => remove(player)}>{t('Delete')}</button></td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</Panel>

{#each approved as site (site.id)}
  {#if players.length && unmapped(site).length}
    <Panel title={t('Not assigned at {site}', { site: site.name })}>
      <table>
        <tbody>
          {#each unmapped(site) as local (local)}
            {@const same = sameName(local)}
            <tr>
              <td>{shownName(local)}</td>
              <td class="num">
                {#if same}
                  <button type="button" class="btn small" onclick={() => choose(same, site, local)}>{t('Same name: {name}', { name: same.name })}</button>
                {:else}
                  <span class="note">{t('No circle player of this name')}</span>
                {/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </Panel>
  {/if}
{/each}

<style>
  .scroll { overflow-x: auto; }
  .cell { white-space: nowrap; }
  .cell input[type='checkbox'] { margin-right: 0.5rem; vertical-align: middle; }
  .cell :global(select.pick) { width: 9.5rem; }
</style>
