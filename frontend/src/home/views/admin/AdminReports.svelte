<script>
  import { onMount } from 'svelte';
  import { t } from '../../../lib/i18n.js';
  // The anonymous usage reports (#58) of the last days: installations, versions, platforms, counts by type and the newest events.
  import Panel from '../../../lib/components/Panel.svelte';
  import { adminCall } from '../../../lib/admin.js';

  let days = $state(7);
  let reports = $state(null);
  let error = $state('');

  async function load() {
    try {
      reports = await adminCall('GET', `/admin/reports?days=${days}`);
      error = '';
    } catch (e) {
      error = t(e.message);
    }
  }

  const installs = (n) => (n === 1 ? t('1 installation') : t('{n} installations', { n }));
  const when = (iso) => new Date(iso).toLocaleString('en-GB', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });

  onMount(load);
</script>

{#if error}<p class="note error">{error}</p>{/if}
<Panel title={t('Reports')}>
  <div class="row wide">
    <select bind:value={days} onchange={load} aria-label={t('Days')}>
      {#each [1, 7, 30, 90, 365] as d (d)}<option value={d}>{d === 1 ? t('last day') : t('last {n} days', { n: d })}</option>{/each}
    </select>
    <button type="button" class="btn" onclick={load}>{t('Refresh')}</button>
  </div>
  {#if reports}
    <p class="note">{reports.installs === 1 ? t('1 installation reported') : t('{n} installations reported', { n: reports.installs })}</p>
    <table>
      <thead><tr><th>{t('Type')}</th><th class="num">{t('Count')}</th></tr></thead>
      <tbody>{#each reports.by_type as row (row.type)}<tr><td>{row.type}</td><td class="num">{row.n}</td></tr>{/each}</tbody>
    </table>
  {/if}
</Panel>

{#if reports}
  <Panel title={t('Versions and platforms')}>
    <table>
      <tbody>
        {#each reports.versions as row (row.version)}<tr><td>{row.version}</td><td class="num">{installs(row.installs)}</td></tr>{/each}
        {#each reports.platforms as row (row.platform)}<tr><td>{row.platform}</td><td class="num">{installs(row.installs)}</td></tr>{/each}
      </tbody>
    </table>
  </Panel>

  <Panel title={t('Newest events')}>
    {#if !reports.recent.length}
      <p class="empty">{t('No event in this time.')}</p>
    {:else}
      <table>
        <thead><tr><th>{t('When')}</th><th>{t('Type')}</th><th>{t('Installation')}</th><th>{t('Version')}</th><th>{t('Details')}</th></tr></thead>
        <tbody>
          {#each reports.recent as event (event.id)}
            <tr><td>{when(event.received_at)}</td><td>{event.type}</td><td class="mono">{event.install_id.slice(0, 8)}</td><td>{event.version}</td><td class="mono">{JSON.stringify(event.data)}</td></tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </Panel>
{/if}
