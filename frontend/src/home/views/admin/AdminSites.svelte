<script>
  import { t } from '../../../lib/i18n.js';
  // The registered locations: what each reported (version, players, last time seen) and the approval that puts a site into the circle.
  import Panel from '../../../lib/components/Panel.svelte';
  import { confirmDialog } from '../../../lib/confirm.js';
  import { ago } from '../../../lib/admin.js';
  import { shownName } from '../../../lib/util.js';

  let { sites, act, reload } = $props();

  async function remove(site) {
    if (!await confirmDialog(t('Take {name} out of the circle? Its mappings stay, it can no longer send or fetch matches.', { name: site.name }))) return;
    await act('POST', `/admin/sites/${site.id}/remove`, {});
  }
</script>

<Panel title={t('Sites')}>
  <p class="note">{t('Every installation that registered at the relay shows up here. Approve the ones of your friends: the short id is what the operator of the site tells you.')}
    <button type="button" class="btn small" onclick={reload}>{t('Refresh')}</button></p>
  {#if !sites.length}
    <p class="empty">{t('No site has registered yet.')}</p>
  {:else}
    <table>
      <thead><tr><th>{t('Site')}</th><th>{t('Seen')}</th><th>{t('Version')}</th><th>{t('Players')}</th><th></th></tr></thead>
      <tbody>
        {#each sites as site (site.id)}
          <tr>
            <td><strong>{site.name}</strong> <span class="mono">{site.id.slice(0, 8)}</span>
              {#if site.approved}<span class="tag ok">{t('approved')}</span>{/if}</td>
            <td>{ago(site.last_seen, t)}</td>
            <td>{site.version || '—'}</td>
            <td>{site.players.length ? site.players.map(shownName).join(', ') : '—'}</td>
            <td class="num">
              {#if site.approved}
                <button type="button" class="btn small" onclick={() => remove(site)}>{t('Remove')}</button>
              {:else}
                <button type="button" class="btn small primary" onclick={() => act('POST', `/admin/sites/${site.id}/approve`, {})}>{t('Approve')}</button>
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</Panel>
