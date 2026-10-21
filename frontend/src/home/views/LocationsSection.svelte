<script>
  import { onMount } from 'svelte';
  import { confirmDialog } from '../../lib/confirm.js';
  import { apiJson } from '../../lib/api.js';
  import { t } from '../../lib/i18n.js';
  // Settings → Connections → Location Online Settings: this installation as a location at the relay. It is registered
  // once with a name and a local PIN; an invitation code links it to another location (a friend, a club). Everything
  // that changes the location or its links asks for the PIN in a pop-up. The list of links is fetched when the
  // section opens and on Refresh.

  let info = $state(null);
  let links = $state(null);
  let name = $state('');
  let pin = $state('');              // the PIN chosen when registering
  let invitation = $state('');
  let joinCode = $state('');
  let error = $state('');
  let message = $state('');
  let busy = $state(false);
  let dialog = $state(null);         // the pop-up: { title, text, fields: [{ label, placeholder, type, value }], run }, null while closed

  async function loadStatus() {
    try {
      info = await apiJson('GET', '/api/locations');
      if (info.registered) await loadLinks();
    } catch (e) {
      console.error('loadStatus failed:', e);
    }
  }

  async function loadLinks() {
    const res = await apiJson('GET', '/api/locations/links');
    if (res.error) { error = res.error; return; }
    if (!Array.isArray(res.links)) { error = t('Unexpected answer from Breakfast. Restart it and reload this page.'); return; }
    links = res.links;
  }

  async function call(method, url, body, done) {
    busy = true; error = ''; message = '';
    try {
      const res = await apiJson(method, url, body);
      if (res.error) { error = res.error; return null; }
      if (res.ok !== true) { error = t('Unexpected answer from Breakfast. Restart it and reload this page.'); return null; }
      if (done) message = done;
      return res;
    } catch (e) {
      error = String(e);
      return null;
    } finally {
      busy = false;
    }
  }

  const pinField = (label) => ({ label: '', placeholder: label, type: 'password', value: '' });

  // Opens the pop-up with its input fields. `run(values)` does the action with the values in the order of the
  // fields and returns true when it worked (the pop-up closes then).
  function ask(title, fields, run, text = '') {
    error = ''; message = '';
    dialog = { title, text, fields, run };
  }

  const askPin = (run) => ask(t('Enter your PIN'), [pinField(t('PIN'))], (v) => run(v[0]));

  const dialogReady = () => dialog && dialog.fields.every((f) => f.value.trim());

  async function submitPin() {
    if (!dialogReady() || busy) return;
    if (await dialog.run(dialog.fields.map((f) => f.value))) dialog = null;
  }

  function onKey(e) {
    if (!dialog) return;
    if (e.key === 'Escape') { e.preventDefault(); dialog = null; }
    else if (e.key === 'Enter') { e.preventDefault(); submitPin(); }
  }

  async function register() {
    if (await call('POST', '/api/locations/register', { name, pin }, t('Registered.'))) {
      pin = '';
      await loadStatus();
    }
  }

  async function setPin() {
    if (await call('POST', '/api/locations/pin', { pin }, t('PIN set.'))) {
      pin = '';
      await loadStatus();
    }
  }

  async function rename([newName, current]) {
    const ok = await call('POST', '/api/locations/rename', { name: newName, pin: current }, t('Renamed.'));
    if (ok) await loadStatus();
    return !!ok;
  }

  async function changePin([current, newPin, again]) {
    if (newPin !== again) { error = t('The new PINs do not match.'); return false; }
    return !!(await call('POST', '/api/locations/change-pin', { pin: current, new_pin: newPin }, t('PIN changed.')));
  }

  async function unregister(current) {
    const ok = await call('POST', '/api/locations/unregister', { pin: current }, t('Signed off.'));
    if (ok) { links = null; invitation = ''; name = ''; await loadStatus(); }
    return !!ok;
  }

  async function invite(current) {
    invitation = '';
    const res = await call('POST', '/api/locations/invite', { pin: current });
    if (res) {
      invitation = res.code;
      message = t('Send this code to the other location. It works once and for 7 days.');
    }
    await loadStatus();
    return !!res;
  }

  async function join(current) {
    const res = await call('POST', '/api/locations/join', { code: joinCode, pin: current });
    if (res) { message = t('Linked with {name}.', { name: res.link.peer.name }); joinCode = ''; }
    await loadStatus();
    return !!res;
  }

  async function unlink(link, current) {
    const ok = await call('POST', '/api/locations/unlink', { link_id: link.link_id, pin: current }, t('Link removed.'));
    if (ok) await loadStatus();
    return !!ok;
  }

  async function confirmUnlink(link) {
    if (await confirmDialog(t('Remove the link with {name}?', { name: link.peer.name }))) askPin((current) => unlink(link, current));
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(invitation);
      message = t('Copied.');
    } catch {
      message = t('Select the code and copy it.');
    }
  }

  const focusFirst = (node, first) => { if (first) node.focus(); };
  const noEnter = (e) => { if (e.key === 'Enter') e.preventDefault(); };

  onMount(loadStatus);
</script>

{#if info?.available}
  <div class="section">
    <div class="title">{t('Location Online Settings')}</div>
    {#if !info.registered}
      <p class="note">{t('Register this installation online. Choose a local PIN of 4 to 8 digits.')}</p>
      {#if !info.relay_configured}
        <p class="note warn">{t('Set the relay address under Online Elimination first.')}</p>
      {/if}
      <div class="row"><label for="locName">{t('Name')}</label><input type="text" id="locName" maxlength="24" placeholder={t('e.g. Home')} bind:value={name} onkeydown={noEnter}></div>
      <div class="row"><label for="locPin">{t('PIN')}</label><input type="password" id="locPin" inputmode="numeric" autocomplete="off" maxlength="8" bind:value={pin} onkeydown={noEnter}></div>
      <button type="button" class="btn" disabled={busy || !info.relay_configured || !name.trim() || !pin} onclick={register}>{t('Register')}</button>
    {:else}
      <p class="name">{t('Location Name')}: <strong>{info.name}</strong></p>
      {#if !info.pin_set}
        <p class="note warn">{t('No PIN is set. Choose a PIN of 4 to 8 digits.')}</p>
        <div class="row wide"><input type="password" inputmode="numeric" autocomplete="off" maxlength="8" placeholder={t('New PIN')} aria-label={t('New PIN')} bind:value={pin} onkeydown={noEnter}><button type="button" class="btn" disabled={busy || !pin} onclick={setPin}>{t('Set PIN')}</button></div>
      {:else}
        <div class="part">
          <div class="title sub">{t('Invite a location')}</div>
          <button type="button" class="btn" disabled={busy} onclick={() => askPin(invite)}>{t('Create invitation')}</button>
          {#if invitation}
            <div class="row wide code-row"><input type="text" class="code" readonly value={invitation} aria-label={t('Invitation code')} onfocus={(e) => e.currentTarget.select()}><button type="button" class="btn" onclick={copy}>{t('Copy')}</button></div>
          {/if}
        </div>

        <div class="part">
          <div class="title sub">{t('Accept an invitation')}</div>
          <div class="row wide"><input type="text" id="locJoin" autocomplete="off" placeholder="BF1-…" aria-label={t('Invitation')} bind:value={joinCode} onkeydown={noEnter}><button type="button" class="btn" disabled={busy || !joinCode.trim()} onclick={() => askPin(join)}>{t('Link')}</button></div>
        </div>
      {/if}

      <div class="part">
        <div class="title sub">{t('Linked locations')} <button type="button" class="btn small" onclick={loadLinks}>{t('Refresh')}</button></div>
        {#if links && links.length}
          {#each links as link (link.link_id)}
            <div class="link"><span>{link.peer.name}</span><button type="button" class="btn small" disabled={busy || !info.pin_set} onclick={() => confirmUnlink(link)}>{t('Remove')}</button></div>
          {/each}
        {:else}
          <p class="note">{t('No linked locations yet.')}</p>
        {/if}
      </div>

      {#if info.pin_set}
        <div class="part">
          <div class="title sub">{t('Location changes')}</div>
          <div class="buttons">
            <button type="button" class="btn" disabled={busy} onclick={() => ask(t('Rename location'), [{ label: t('Name'), placeholder: '', type: 'text', value: info.name }, pinField(t('PIN'))], rename)}>{t('Rename')}</button>
            <button type="button" class="btn" disabled={busy} onclick={() => ask(t('Change PIN'), [pinField(t('Old PIN')), pinField(t('New PIN')), pinField(t('Repeat new PIN'))], changePin)}>{t('Change PIN')}</button>
            <button type="button" class="btn" disabled={busy} onclick={() => ask(t('Sign off?'), [pinField(t('PIN'))], ([current]) => unregister(current), t('Sign off and close connections to other locations?'))}>{t('Sign off')}</button>
          </div>
        </div>
      {/if}
    {/if}
    {#if error && !dialog}<p class="note error">{error}</p>{/if}
    {#if message}<p class="note">{message}</p>{/if}
  </div>
{/if}

<svelte:window onkeydown={onKey} />

{#if dialog}
  <div class="pin-overlay">
    <button type="button" class="pin-backdrop" aria-label={t('Cancel')} onclick={() => (dialog = null)}></button>
    <div class="pin-box" role="dialog" aria-modal="true" aria-label={dialog.title}>
      <p class="pin-text">{dialog.title}</p>
      {#if dialog.text}<p class="pin-note">{dialog.text}</p>{/if}
      {#each dialog.fields as field, i}
        {#if field.label}<label class="pin-label" for="dlgField{i}">{field.label}</label>{/if}
        {#if field.type === 'password'}
          <input type="password" id="dlgField{i}" class="pin-input" inputmode="numeric" autocomplete="off" maxlength="8" placeholder={field.placeholder} aria-label={field.placeholder || field.label} use:focusFirst={i === 0} bind:value={field.value}>
        {:else}
          <input type="text" id="dlgField{i}" class="pin-input" maxlength="24" autocomplete="off" placeholder={field.placeholder} aria-label={field.placeholder || field.label} use:focusFirst={i === 0} bind:value={field.value}>
        {/if}
      {/each}
      {#if error}<p class="note error">{error}</p>{/if}
      <div class="pin-actions">
        <button type="button" class="pin-btn" onclick={() => (dialog = null)}>{t('Cancel')}</button>
        <button type="button" class="pin-btn yes" disabled={busy || !dialogReady()} onclick={submitPin}>{t('OK')}</button>
      </div>
    </div>
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
  .title.sub { margin: 0 0 0.75rem; }
  .name { margin: 0 0 1rem; font-size: 0.95rem; color: var(--text); }
  .part { border-top: 1px solid var(--glass-border); padding-top: 1rem; margin-top: 1rem; }
  .buttons { display: flex; flex-wrap: wrap; gap: 0.5rem; }
  .code-row { margin-top: 0.75rem; margin-bottom: 0; }
  .row { display: grid; grid-template-columns: 8rem 1fr; align-items: center; gap: 0.5rem; margin-bottom: 0.65rem; }
  .row label { font-size: 0.9rem; color: color-mix(in srgb, var(--text) 72%, transparent); }
  .row input {
    width: 100%; background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border);
    border-radius: 10px; color: var(--text); padding: 0.45rem 0.75rem; font-size: 0.9rem; font-family: inherit;
  }
  .row input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 25%, transparent); }
  .row.wide { grid-template-columns: 1fr auto; }
  .row input.code { font-family: monospace; font-size: 0.8rem; }
  .actions { margin-bottom: 0.65rem; }
  .link { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; margin-bottom: 0.5rem; font-size: 0.9rem; }
  .note { font-size: 0.75rem; color: var(--muted); margin: 0 0 0.5rem; }
  .note.warn { color: var(--yellow); }
  .note.error { color: var(--red); }
  .btn { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 8px; padding: 0.5rem 1rem; font-size: 0.9rem; font-weight: 600; font-family: inherit; cursor: pointer; transition: opacity 0.15s; }
  .btn.small { padding: 0.25rem 0.7rem; font-size: 0.8rem; text-transform: none; letter-spacing: 0; }
  .btn:hover { opacity: 0.85; }
  .btn:disabled { opacity: 0.4; cursor: default; }
  .pin-overlay { position: fixed; inset: 0; z-index: 400; display: flex; align-items: center; justify-content: center; padding: 1.5rem 1rem; }
  .pin-backdrop { position: absolute; inset: 0; background: rgba(3, 8, 20, 0.6); backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px); border: none; padding: 0; cursor: default; }
  .pin-box { position: relative; width: 100%; max-width: 360px; padding: 1.5rem 1.5rem 1.25rem; border-radius: 20px; background: var(--surface); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); }
  .pin-text { margin: 0 0 1rem; font-size: 1.15rem; font-weight: 600; color: var(--text); }
  .pin-note { margin: -0.5rem 0 1rem; font-size: 0.9rem; color: var(--muted); }
  .pin-label { display: block; margin: 0 0 0.3rem; font-size: 0.8rem; color: var(--muted); }
  .pin-input {
    width: 100%; box-sizing: border-box; margin-bottom: 0.7rem; background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border);
    border-radius: 10px; color: var(--text); padding: 0.55rem 0.75rem; font-size: 1rem; font-family: inherit;
  }
  .pin-input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 25%, transparent); }
  .pin-actions { display: flex; gap: 0.8rem; }
  .pin-btn {
    flex: 1; padding: 0.7rem 1rem; border-radius: 999px; font-family: inherit; font-size: 1rem; font-weight: 600; cursor: pointer;
    background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2);
  }
  .pin-btn:hover { border-color: var(--accent); color: var(--accent); }
  .pin-btn.yes { background: #166534; border-color: transparent; color: #fff; }
  .pin-btn.yes:hover { background: #15803d; color: #fff; }
  .pin-btn:disabled { opacity: 0.4; cursor: default; }
  @media (max-width: 520px) {
    .row { grid-template-columns: 1fr; }
  }
</style>
