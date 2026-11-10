<script>
  import { onDestroy, onMount } from 'svelte';
  import { confirmDialog, pinDialog } from '../../lib/confirm.js';
  import { apiJson } from '../../lib/api.js';
  import { t } from '../../lib/i18n.js';
  // Settings → Connections → Breakfast Cloud: the account this installation belongs to. A registered location asks
  // the server for a code and shows it as text and QR code; the user confirms it in the portal, and this section sees
  // it on its next question. A location that is still at a relay without accounts can move to a Breakfast Cloud
  // server here: its identity stays, only the address changes.

  let { onmoved = null } = $props();

  let location = $state(null);
  let cloud = $state(null);
  let pairing = $state(null);        // the open code: { code, url, qr, until }
  let address = $state('');
  let error = $state('');
  let message = $state('');
  let busy = $state(false);
  let timer = null;

  async function load() {
    try {
      location = await apiJson('GET', '/api/locations');
      cloud = location.registered ? await apiJson('GET', '/api/cloud') : null;
    } catch (e) {
      console.error('load failed:', e);
    }
  }

  async function call(url, body) {
    busy = true; error = ''; message = '';
    try {
      const res = await apiJson('POST', url, body);
      if (res.error) { error = res.error; return null; }
      if (res.ok !== true) { error = t('Unexpected answer from Breakfast. Restart it and reload this page.'); return null; }
      return res;
    } catch (e) {
      error = String(e);
      return null;
    } finally {
      busy = false;
    }
  }

  function stopWaiting() {
    clearInterval(timer);
    timer = null;
    pairing = null;
  }

  // Asks the server whether the code was confirmed, until it was or the code ran out.
  async function check() {
    if (!pairing) return;
    if (Date.now() > pairing.until) {
      stopWaiting();
      error = t('The code ran out. Create a new one.');
      return;
    }
    try {
      const now = await apiJson('GET', '/api/cloud');
      if (now.paired) {
        cloud = now;
        stopWaiting();
        message = t('Paired with {email}.', { email: now.email });
      }
    } catch (e) { /* asked again in a moment */ }
  }

  async function pair() {
    const pin = await pinDialog(t('Enter your PIN'));
    if (!pin) return;
    const res = await call('/api/cloud/pair', { pin });
    if (!res) return;
    stopWaiting();
    pairing = { code: res.code, url: res.url, qr: res.qr || '', until: Date.now() + res.expires_in_s * 1000 };
    timer = setInterval(check, Math.max(2, res.interval_s) * 1000);
  }

  async function unpair() {
    if (!await confirmDialog(t('Unpair this installation from {email}?', { email: cloud.email }))) return;
    const pin = await pinDialog(t('Enter your PIN'));
    if (!pin) return;
    if (await call('/api/cloud/unpair', { pin })) {
      message = t('Unpaired.');
      await load();
    }
  }

  async function switchServer() {
    if (!await confirmDialog(t('Move this location to {address}? Online play, the circle and the voice chats use that server from then on.', { address: address.trim() }))) return;
    const pin = await pinDialog(t('Enter your PIN'));
    if (!pin) return;
    const res = await call('/api/cloud/switch', { address: address.trim(), pin });
    if (res) {
      onmoved?.(res);
      address = '';
      await load();
      message = t('Moved. This location now uses the new server.');
    }
  }

  const noEnter = (e) => { if (e.key === 'Enter') e.preventDefault(); };

  onMount(load);
  onDestroy(() => clearInterval(timer));
</script>

{#if location?.registered && location.pin_set && cloud}
  <div class="section">
    <div class="title">{t('Breakfast Cloud')} <button type="button" class="btn small" onclick={load}>{t('Refresh')}</button></div>
    {#if cloud.available}
      {#if cloud.paired}
        <p class="name">{t('Account')}: <strong>{cloud.email}</strong></p>
        <button type="button" class="btn" disabled={busy} onclick={unpair}>{t('Unpair')}</button>
      {:else}
        <p class="note">{t('Pair this installation with your account: create a code and confirm it in the portal.')}</p>
        <button type="button" class="btn" disabled={busy} onclick={pair}>{pairing ? t('New code') : t('Pair')}</button>
        {#if pairing}
          <div class="pairing">
            {#if pairing.qr}<div class="qr" role="img" aria-label={t('QR code of the pairing page')}>{@html pairing.qr}</div>{/if}
            <div>
              <p class="code">{pairing.code}</p>
              <p class="note">{t('Scan the QR code or open the portal, log in and type the code. It is valid for 10 minutes.')}</p>
              <p class="note"><a href={pairing.url} target="_blank" rel="noopener noreferrer">{pairing.url}</a></p>
              <p class="note">{t('Waiting for the confirmation…')}</p>
            </div>
          </div>
        {/if}
      {/if}
    {:else if cloud.error}
      <p class="note warn">{cloud.error}</p>
    {:else}
      <p class="note">{t('This location is at a relay without accounts. Once its data has been moved to a Breakfast Cloud server, enter the address of that server: the location keeps its name, its links and its circle.')}</p>
      <div class="row wide"><input type="text" autocomplete="off" placeholder="cloud.example.org" aria-label={t('Server address')} bind:value={address} onkeydown={noEnter}><button type="button" class="btn" disabled={busy || !address.trim()} onclick={switchServer}>{t('Move')}</button></div>
    {/if}
    {#if error}<p class="note error">{error}</p>{/if}
    {#if message}<p class="note">{message}</p>{/if}
  </div>
{/if}

<style>
  .section {
    background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur);
    border-radius: 16px; padding: 1.25rem 1.4rem; margin-bottom: 1.25rem;
  }
  .title {
    font-size: 0.78rem; color: var(--muted); font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em;
    margin-bottom: 1rem; display: flex; align-items: center; gap: 0.5rem;
  }
  .name { margin: 0 0 1rem; font-size: 0.95rem; color: var(--text); }
  .pairing { display: flex; flex-wrap: wrap; gap: 1.25rem; align-items: flex-start; margin-top: 1rem; }
  .qr { width: 200px; max-width: 100%; background: #fff; border-radius: 4px; }
  .qr :global(svg) { display: block; width: 100%; height: auto; }
  .code { font-family: monospace; font-size: 1.8rem; font-weight: 700; letter-spacing: 0.08em; color: var(--text); margin: 0 0 0.6rem; }
  .row { display: grid; align-items: center; gap: 0.5rem; margin-bottom: 0.65rem; }
  .row.wide { grid-template-columns: 1fr auto; }
  .row input {
    width: 100%; background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border);
    border-radius: 10px; color: var(--text); padding: 0.45rem 0.75rem; font-size: 0.9rem; font-family: inherit;
  }
  .row input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 25%, transparent); }
  .note { font-size: 0.75rem; color: var(--muted); margin: 0 0 0.5rem; }
  .note a { color: var(--accent); word-break: break-all; }
  .note.warn { color: var(--yellow); }
  .note.error { color: var(--red); margin-top: 0.75rem; }
  .btn { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 8px; padding: 0.5rem 1rem; font-size: 0.9rem; font-weight: 600; font-family: inherit; cursor: pointer; transition: opacity 0.15s; }
  .btn.small { padding: 0.25rem 0.7rem; font-size: 0.8rem; text-transform: none; letter-spacing: 0; }
  .btn:hover { opacity: 0.85; }
  .btn:disabled { opacity: 0.4; cursor: default; }
  @media (max-width: 520px) {
    .row.wide { grid-template-columns: 1fr; }
  }
</style>
