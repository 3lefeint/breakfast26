<script>
  import { onMount } from 'svelte';
  import { t } from '../../../lib/i18n.js';
  // The usage of the free plan of Cloudflare as the relay reads it from the GraphQL Analytics API: each figure against its
  // limit. A figure the API does not give shows its error, the others stay.
  import Panel from '../../../lib/components/Panel.svelte';
  import { adminCall } from '../../../lib/admin.js';

  let usage = $state(null);
  let error = $state('');
  let busy = $state(false);

  async function load() {
    busy = true;
    try {
      usage = await adminCall('GET', '/admin/usage');
      error = '';
    } catch (e) {
      error = t(e.message);
    } finally {
      busy = false;
    }
  }

  const number = (n) => Math.round(n).toLocaleString('en-GB');
  const size = (bytes) => (bytes >= 1e9 ? `${(bytes / 1e9).toFixed(2)} GB` : bytes >= 1e6 ? `${(bytes / 1e6).toFixed(1)} MB` : `${Math.round(bytes / 1e3)} KB`);
  const percent = (used, limit) => Math.min(100, (used / limit) * 100);
  const level = (used, limit) => (used / limit >= 0.9 ? 'high' : used / limit >= 0.7 ? 'mid' : 'low');

  // The rows of the table: a label, what is used, the limit and how to write both.
  let rows = $derived(!usage?.configured ? [] : [
    { key: 'workers', label: t('Worker requests today'), part: usage.workers, used: (d) => d.requests, limit: usage.limits.workers_requests_day, show: number },
    { key: 'd1', label: t('D1 rows read today'), part: usage.d1, used: (d) => d.rows_read, limit: usage.limits.d1_rows_read_day, show: number },
    { key: 'd1w', label: t('D1 rows written today'), part: usage.d1, used: (d) => d.rows_written, limit: usage.limits.d1_rows_written_day, show: number },
    { key: 'd1s', label: t('D1 database size'), part: usage.d1_size, used: (d) => d.bytes, limit: usage.limits.d1_database_bytes, show: size },
    { key: 'r2a', label: t('R2 Class A operations this month'), part: usage.r2_operations, used: (d) => d.class_a, limit: usage.limits.r2_class_a_month, show: number },
    { key: 'r2b', label: t('R2 Class B operations this month'), part: usage.r2_operations, used: (d) => d.class_b, limit: usage.limits.r2_class_b_month, show: number },
    { key: 'r2s', label: t('R2 storage'), part: usage.r2_storage, used: (d) => d.bytes, limit: usage.limits.r2_storage_bytes, show: size },
  ]);

  onMount(load);
</script>

{#if error}<p class="note error">{error}</p>{/if}
<Panel title={t('Usage of the free plan')}>
  <p class="note">{t('Read from Cloudflare when this tab opens. Today and this month are counted in UTC.')}
    <button type="button" class="btn small" disabled={busy} onclick={load}>{t('Refresh')}</button></p>
  {#if usage && !usage.configured}
    <p class="empty">{t('The relay cannot read its usage yet: it needs the account id and an analytics token (see the README of the relay).')}</p>
  {:else if usage}
    <table>
      <thead><tr><th>{t('Figure')}</th><th class="num">{t('Used')}</th><th class="num">{t('Limit')}</th><th class="bar-head"></th></tr></thead>
      <tbody>
        {#each rows as row (row.key)}
          <tr>
            <td>{row.label}</td>
            {#if row.part.error}
              <td colspan="3" class="note error">{row.part.error}</td>
            {:else}
              {@const used = row.used(row.part.data)}
              <td class="num">{row.show(used)}</td>
              <td class="num">{row.show(row.limit)}</td>
              <td class="bar-cell"><span class="bar"><span class="fill {level(used, row.limit)}" style="width: {percent(used, row.limit)}%"></span></span></td>
            {/if}
          </tr>
        {/each}
      </tbody>
    </table>
    {#if !usage.workers.error}
      <p class="note spaced">{t('Worker errors today')}: {number(usage.workers.data.errors)} · {t('CPU time P50 / P99 (as the API gives it, no unit)')}: {number(usage.workers.data.cpu_p50)} / {number(usage.workers.data.cpu_p99)}</p>
    {/if}
    {#if !usage.r2_operations.error && usage.r2_operations.data.other}
      <p class="note">{t('R2 operations not counted as Class A or B: {n}', { n: number(usage.r2_operations.data.other) })}</p>
    {/if}
  {/if}
</Panel>

<style>
  .bar-head { width: 30%; }
  .bar-cell { width: 30%; }
  .bar { display: block; height: 0.6rem; border-radius: 999px; background: rgba(0, 0, 0, 0.3); overflow: hidden; }
  .fill { display: block; height: 100%; border-radius: 999px; }
  .fill.low { background: var(--green); }
  .fill.mid { background: var(--yellow); }
  .fill.high { background: var(--red); }
  .spaced { margin-top: 0.9rem; }
</style>
