<script>
  import { onMount } from 'svelte';
  import { t } from '../../../lib/i18n.js';
  // The links between the sites of the circle, as one table: a row and a column per approved site, a tick where two sites are linked.
  // The table is symmetric (one link per pair), the diagonal stays empty. A link made by an invitation shows a dot; unticking it removes it too.
  import Panel from '../../../lib/components/Panel.svelte';
  import { adminCall } from '../../../lib/admin.js';

  let sites = $state([]);
  let links = $state([]);
  let error = $state('');

  async function load() {
    try {
      const res = await adminCall('GET', '/admin/links');
      sites = res.sites;
      links = res.links;
      error = '';
    } catch (e) {
      error = t(e.message);
    }
  }

  async function tick(a, b, linked) {
    try {
      await adminCall('PUT', `/admin/links/${a.id}/${b.id}`, { linked });
      error = '';
    } catch (e) {
      error = t(e.message);
    } finally {
      await load();
    }
  }

  const linkOf = (a, b) => links.find((l) => (l.a === a.id && l.b === b.id) || (l.a === b.id && l.b === a.id));

  onMount(load);
</script>

<Panel title={t('Linked locations')}>
  <p class="note">{t('Tick the sites that are linked. A linked pair can play online matches and see its open matches. A dot marks a link made by an invitation.')}</p>
  {#if error}<p class="note error">{error}</p>{/if}
  {#if sites.length < 2}
    <p class="empty">{t('Approve at least two sites first, then they can be linked here.')}</p>
  {:else}
    <div class="scroll">
      <table>
        <thead>
          <tr><th>{t('Site')}</th>{#each sites as site (site.id)}<th class="cell">{site.name}</th>{/each}</tr>
        </thead>
        <tbody>
          {#each sites as row (row.id)}
            <tr>
              <td><strong>{row.name}</strong></td>
              {#each sites as col (col.id)}
                <td class="cell">
                  {#if row.id === col.id}
                    <span class="self" aria-hidden="true">–</span>
                  {:else}
                    {@const link = linkOf(row, col)}
                    <input type="checkbox" checked={!!link} aria-label={`${row.name} ↔ ${col.name}`} onchange={(e) => tick(row, col, e.currentTarget.checked)}>
                    {#if link && link.source === 'invitation'}<span class="dot" title={t('Made by an invitation')}>●</span>{/if}
                  {/if}
                </td>
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</Panel>

<style>
  .scroll { overflow-x: auto; }
  .cell { text-align: center; }
  .scroll :global(th.cell) { text-align: center; }       /* the admin area sets its th to the left, this one is stronger */
  .self { color: var(--muted, #888); }
  .dot { font-size: 0.5rem; margin-left: 0.2rem; vertical-align: middle; color: var(--accent); }
</style>
