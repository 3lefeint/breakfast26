<script>
  import { onMount } from 'svelte';
  import { t } from '../../lib/i18n.js';
  // The admin of the circle: the sites, the players of the circle with the mapping of the players of each site to them, the rules
  // (which sites get the matches of a player), the sync state and the usage reports. It talks to the relay directly from the browser
  // (lib/admin.js): the address is remembered, the password is typed per session and never stored.
  import PageHeader from '../../lib/components/PageHeader.svelte';
  import Panel from '../../lib/components/Panel.svelte';
  import { adminRelay, adminLoggedIn, adminLogin, adminLogout, adminForget, adminCall, relayBase } from '../../lib/admin.js';
  import AdminSites from './admin/AdminSites.svelte';
  import AdminPlayers from './admin/AdminPlayers.svelte';
  import AdminSync from './admin/AdminSync.svelte';
  import AdminReports from './admin/AdminReports.svelte';
  import AdminUsage from './admin/AdminUsage.svelte';

  let address = $state($adminRelay);
  let password = $state('');
  let error = $state('');
  let busy = $state(false);
  let tab = $state('sites');
  let sites = $state([]);
  let players = $state([]);

  const TABS = [
    { id: 'sites', label: t('Sites') },
    { id: 'players', label: t('Players') },
    { id: 'sync', label: t('Sync') },
    { id: 'reports', label: t('Reports') },
    { id: 'usage', label: t('Usage') },
  ];

  async function signIn() {
    busy = true; error = '';
    try {
      await adminLogin(address, password);
      password = '';
      await load();
    } catch (e) {
      error = t(e.message);
    } finally {
      busy = false;
    }
  }

  // Loads the two lists every tab works with; a call that fails shows its error (a login that ran out sends the admin back to the form).
  async function load() {
    try {
      sites = (await adminCall('GET', '/admin/sites')).sites;
      players = (await adminCall('GET', '/admin/players')).players;
      error = '';
    } catch (e) {
      error = t(e.message);
    }
  }

  // Actions on the relay in a row, [method, path, body] each, then the lists again; false when one of them failed.
  async function actAll(calls) {
    error = '';
    let done = true;
    for (const [method, path, body] of calls) {
      try {
        await adminCall(method, path, body);
      } catch (e) {
        error = t(e.message);
        done = false;
        break;
      }
    }
    await load();
    return done;
  }

  const act = (method, path, body) => actAll([[method, path, body]]);

  let approved = $derived(sites.filter((s) => s.approved));
  let known = $derived(!!relayBase($adminRelay));

  onMount(() => { if ($adminLoggedIn) load(); });
</script>

<PageHeader title={t('Admin')} back="#home" />

<div class="admin">
  {#if !$adminLoggedIn}
    <Panel title={t('Log in')}>
      <p class="note">{t('The admin of the circle manages the sites of the friends from here. Log in only on installations you run yourself: the password is typed here and sent to the relay, nothing of it is stored.')}</p>
      <div class="row"><label for="adminRelay">{t('Relay address')}</label><input id="adminRelay" type="text" placeholder="https://" bind:value={address} onkeydown={(e) => e.key === 'Enter' && signIn()}></div>
      <div class="row"><label for="adminPassword">{t('Password')}</label><input id="adminPassword" type="password" autocomplete="off" bind:value={password} onkeydown={(e) => e.key === 'Enter' && signIn()}></div>
      <div class="buttons">
        <button type="button" class="btn primary" disabled={busy || !address.trim() || !password} onclick={signIn}>{t('Log in')}</button>
        {#if known}<button type="button" class="btn" onclick={() => { adminForget(); address = ''; }}>{t('Forget this relay')}</button>{/if}
      </div>
      {#if error}<p class="note error">{error}</p>{/if}
    </Panel>
  {:else}
    <div class="topline">
      <span class="note">{$adminRelay}</span>
      <button type="button" class="btn small" onclick={adminLogout}>{t('Log out')}</button>
    </div>
    <div class="chips" role="tablist" aria-label={t('Admin')}>
      {#each TABS as tk (tk.id)}
        <button type="button" role="tab" class="chip" class:active={tab === tk.id} aria-selected={tab === tk.id} onclick={() => (tab = tk.id)}>{tk.label}</button>
      {/each}
    </div>
    {#if error}<p class="note error">{error}</p>{/if}
    {#if tab === 'sites'}
      <AdminSites {sites} {act} reload={load} />
    {:else if tab === 'players'}
      <AdminPlayers {approved} {players} {actAll} />
    {:else if tab === 'sync'}
      <AdminSync />
    {:else if tab === 'usage'}
      <AdminUsage />
    {:else}
      <AdminReports />
    {/if}
  {/if}
</div>

<style>
  .admin :global(.row) { display: grid; grid-template-columns: 9rem 1fr; align-items: center; gap: 0.5rem; margin-bottom: 0.65rem; }
  .admin :global(.row.wide) { grid-template-columns: minmax(8rem, 16rem) auto; justify-content: start; }
  .admin :global(.row label) { font-size: 0.9rem; color: color-mix(in srgb, var(--text) 72%, transparent); }
  .admin :global(input[type='text']), .admin :global(input[type='password']), .admin :global(select) {
    width: 100%; background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border);
    border-radius: 10px; color: var(--text); padding: 0.5rem 0.75rem; font-size: 0.9rem; font-family: inherit;
  }
  .admin :global(input:focus), .admin :global(select:focus) { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 25%, transparent); }
  .admin :global(.buttons) { display: flex; flex-wrap: wrap; gap: 0.5rem; }
  .admin :global(.btn) {
    background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 8px; padding: 0.5rem 1rem;
    font-size: 0.9rem; font-weight: 600; font-family: inherit; cursor: pointer; transition: opacity 0.15s, border-color 0.15s;
  }
  .admin :global(.btn.primary) { background: var(--accent); border-color: var(--accent); color: #0c0c0f; }
  .admin :global(.btn.small) { padding: 0.25rem 0.7rem; font-size: 0.8rem; }
  .admin :global(.btn:hover) { border-color: var(--accent); }
  .admin :global(.btn:disabled) { opacity: 0.4; cursor: default; }
  .admin :global(.note) { font-size: 0.8rem; color: var(--muted); margin: 0 0 0.75rem; }
  .admin :global(.note.error) { color: var(--red); }
  .admin :global(.empty) { color: var(--muted); font-size: 0.9rem; }
  .admin :global(table) { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
  .admin :global(th) { text-align: left; font-size: 0.75rem; color: var(--muted); font-weight: 500; padding: 0.4rem 0.6rem; border-bottom: 1px solid var(--glass-border); }
  .admin :global(td) { padding: 0.5rem 0.6rem; border-bottom: 1px solid var(--glass-border); vertical-align: middle; }
  .admin :global(.num) { text-align: right; }
  .admin :global(.tag) { display: inline-block; font-size: 0.7rem; font-weight: 700; padding: 0.1rem 0.5rem; border-radius: 999px; border: 1px solid var(--glass-border); color: var(--muted); }
  .admin :global(.tag.ok) { color: var(--green); border-color: color-mix(in srgb, var(--green) 50%, transparent); }
  .admin :global(.tag.warn) { color: var(--yellow); border-color: color-mix(in srgb, var(--yellow) 50%, transparent); }
  .admin :global(.mono) { font-family: monospace; font-size: 0.8rem; color: var(--muted); }
  .topline { display: flex; align-items: center; justify-content: space-between; gap: 1rem; margin-bottom: 0.75rem; }
  .chips { display: flex; gap: 0.4rem; margin-bottom: 1.25rem; flex-wrap: wrap; }
  .chip {
    background: var(--glass); border: 1px solid var(--glass-border); color: var(--muted); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2);
    border-radius: 20px; padding: 0.35rem 1rem; font-family: inherit; font-size: 0.85rem; cursor: pointer;
  }
  .chip:hover { border-color: var(--accent); color: var(--text); }
  .chip.active { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); font-weight: 700; }
  @media (max-width: 520px) { .admin :global(.row) { grid-template-columns: 1fr; } }
</style>
