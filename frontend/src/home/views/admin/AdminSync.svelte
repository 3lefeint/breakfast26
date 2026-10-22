<script>
  import { onMount } from 'svelte';
  import { t } from '../../../lib/i18n.js';
  // The sync state per approved site (what it reported, how many records it sent) and the newest records without their content.
  import Panel from '../../../lib/components/Panel.svelte';
  import { adminCall, ago } from '../../../lib/admin.js';

  let sync = $state(null);
  let records = $state([]);
  let error = $state('');

  async function load() {
    try {
      sync = await adminCall('GET', '/admin/sync');
      records = (await adminCall('GET', '/admin/records')).records;
      error = '';
    } catch (e) {
      error = t(e.message);
    }
  }

  const size = (bytes) => (bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`);
  const stateLine = (state) => Object.entries(state || {}).map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' · ') || '—';

  onMount(load);
</script>

{#if error}<p class="note error">{error}</p>{/if}
<Panel title={t('Sync')}>
  <p class="note">{#if sync}{t('{n} records, {size} in all', { n: sync.totals.n, size: size(sync.totals.bytes) })}{/if}
    <button type="button" class="btn small" onclick={load}>{t('Refresh')}</button></p>
  {#if sync && !sync.sites.length}
    <p class="empty">{t('No approved site yet.')}</p>
  {:else if sync}
    <table>
      <thead><tr><th>{t('Site')}</th><th>{t('Seen')}</th><th>{t('Version')}</th><th class="num">{t('Records sent')}</th><th>{t('Reported state')}</th></tr></thead>
      <tbody>
        {#each sync.sites as site (site.id)}
          <tr>
            <td><strong>{site.name}</strong></td>
            <td>{ago(site.last_seen, t)}</td>
            <td>{site.version || '—'}</td>
            <td class="num">{site.records_sent.n}</td>
            <td class="mono">{stateLine(site.state)}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</Panel>

<Panel title={t('Newest records')}>
  {#if !records.length}
    <p class="empty">{t('No record yet.')}</p>
  {:else}
    <table>
      <thead><tr><th>{t('When')}</th><th>{t('Played at')}</th><th>{t('Mode')}</th><th>{t('Players')}</th><th class="num">{t('Revision')}</th><th class="num">{t('Size')}</th></tr></thead>
      <tbody>
        {#each records as record (record.seq)}
          <tr>
            <td>{ago(record.created_at, t)}</td>
            <td>{record.origin.name || record.origin.id.slice(0, 8)}</td>
            <td>{record.game_mode}{record.deleted ? ' · ' + t('deleted') : ''}</td>
            <td>{record.players.join(', ')}</td>
            <td class="num">{record.revision}</td>
            <td class="num">{size(record.size)}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</Panel>
