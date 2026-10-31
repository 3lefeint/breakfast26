<script>
  import { onMount } from 'svelte';
  import { t } from '../../../lib/i18n.js';
  // The voice chat channels of the circle, as one table: a row per approved site, a column per channel. A tick says that the site
  // sees the channel and can enter it from Breakfast. Channels are made and deleted here.
  import Panel from '../../../lib/components/Panel.svelte';
  import { confirmDialog } from '../../../lib/confirm.js';
  import { adminCall } from '../../../lib/admin.js';
  import ChannelDialog from './ChannelDialog.svelte';

  let sites = $state([]);
  let channels = $state([]);
  let name = $state('');
  let error = $state('');
  let editing = $state(null);         // the channel whose small window is open

  async function load() {
    try {
      const res = await adminCall('GET', '/admin/voice');
      sites = res.sites;
      channels = res.channels;
      error = '';
    } catch (e) {
      error = t(e.message);
    }
  }

  async function act(method, path, body) {
    try {
      await adminCall(method, path, body);
      error = '';
      return true;
    } catch (e) {
      error = t(e.message);
      return false;
    } finally {
      await load();
    }
  }

  async function add() {
    const text = name.trim();
    if (!text) return;
    if (await act('POST', '/admin/voice/channels', { name: text })) name = '';
  }

  async function rename(channel, name) {
    if (await act('PUT', `/admin/voice/channels/${channel.id}`, { name })) editing = null;
  }

  async function remove(channel) {
    if (!await confirmDialog(t('Delete the channel {name}?', { name: channel.name }))) return;
    if (await act('DELETE', `/admin/voice/channels/${channel.id}`)) editing = null;
  }

  const ticked = (channel, site) => channel.sites.includes(site.id);
  const tick = (channel, site, visible) => act('PUT', `/admin/voice/channels/${channel.id}/sites/${site.id}`, { visible });

  onMount(load);
</script>

<Panel title={t('Voice chats')}>
  <div class="row wide"><input type="text" maxlength="40" placeholder={t('Name of a channel')} aria-label={t('Name of a channel')} bind:value={name} onkeydown={(e) => e.key === 'Enter' && add()}><button type="button" class="btn primary" disabled={!name.trim()} onclick={add}>{t('Add')}</button></div>
  <p class="note">{t('Tick the sites that see a channel. A site that loses its tick leaves the channel at once.')}</p>
  {#if error}<p class="note error">{error}</p>{/if}
  {#if !channels.length}
    <p class="empty">{t('No channel yet.')}</p>
  {:else if !sites.length}
    <p class="empty">{t('Approve a site first, then it can be ticked here.')}</p>
  {:else}
    <div class="scroll">
      <table>
        <thead>
          <tr><th>{t('Site')}</th>{#each channels as channel (channel.id)}<th class="cell"><button type="button" class="name-link" onclick={() => (editing = channel)}>{channel.name}</button></th>{/each}</tr>
        </thead>
        <tbody>
          {#each sites as site (site.id)}
            <tr>
              <td><strong>{site.name}</strong></td>
              {#each channels as channel (channel.id)}
                <td class="cell"><input type="checkbox" checked={ticked(channel, site)} aria-label={`${channel.name} → ${site.name}`} onchange={(e) => tick(channel, site, e.currentTarget.checked)}></td>
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</Panel>

{#if editing}
  <ChannelDialog channel={editing} onsave={(name) => rename(editing, name)} ondelete={() => remove(editing)} onclose={() => (editing = null)} />
{/if}

<style>
  .scroll { overflow-x: auto; }
  .cell { text-align: center; }
  .scroll :global(th.cell) { text-align: center; }       /* the admin area sets its th to the left, this one is stronger */
  .name-link { background: none; border: none; padding: 0; font: inherit; font-size: 0.85rem; font-weight: 600; color: var(--accent); cursor: pointer; text-decoration: underline; }
  .name-link:hover { color: var(--text); }
</style>
