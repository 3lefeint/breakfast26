<script>
  import { onMount } from 'svelte';
  import { confirmDialog, pinDialog } from '../../lib/confirm.js';
  import { apiJson } from '../../lib/api.js';
  import { t } from '../../lib/i18n.js';
  import { shownName, storedName } from '../../lib/util.js';
  import { players } from '../../lib/stores/players.js';
  // Settings → Connections → Sharing: the members of this location and the memberships of this installation. The admin
  // (behind the PIN of the location) invites a player of this installation and hands him the invitation code; at home
  // *Join a location* takes such a code, asks which player of this installation is the member (the player of the same name
  // is only suggested) and which direction the matches take. No match is sent yet.

  let info = $state(null);          // /api/locations: whether this installation is a location with a PIN
  let sharing = $state(null);       // /api/sharing: consent, members, memberships
  let invitePlayer = $state('');
  let invitation = $state(null);    // {code, player}: the last invitation, shown until the page is left
  let joinCode = $state('');
  let preview = $state(null);       // what the pasted invitation is, with the choice of the player and the direction
  let joinPlayer = $state('');
  let newPlayer = $state('');
  let direction = $state('pull');
  let error = $state('');
  let message = $state('');
  let busy = $state(false);

  const NEW = '__new__';

  async function load() {
    try {
      info = await apiJson('GET', '/api/locations');
      sharing = await apiJson('GET', '/api/sharing');
    } catch (e) {
      console.error('sharing load failed:', e);
    }
  }

  async function call(url, body, done) {
    busy = true; error = ''; message = '';
    try {
      const res = await apiJson('POST', url, body);
      if (res.error) { error = t(res.error); return null; }
      if (done) message = done;
      return res;
    } catch (e) {
      error = String(e);
      return null;
    } finally {
      busy = false;
    }
  }

  let isAdmin = $derived(!!(info?.registered && info?.pin_set));
  let memberNames = $derived(new Set((sharing?.members || []).map((m) => m.player)));
  let candidates = $derived($players.known.filter((n) => !memberNames.has(n)));

  async function invite() {
    if (!invitePlayer) return;
    let confirm = sharing.consent;
    if (!confirm) {
      if (!await confirmDialog(t('The matches of the members, with the players they played against, are stored at this location. Do you confirm?'))) return;
      confirm = true;
    }
    const pin = await pinDialog(t('Enter your PIN'));
    if (pin == null) return;
    const res = await call('/api/sharing/members', { player: invitePlayer, pin, confirm });
    if (res) {
      invitation = { code: res.code, player: invitePlayer };
      message = t('Give this code to {name}. It works once and for 7 days.', { name: shownName(invitePlayer) });
      invitePlayer = '';
    }
    await load();
  }

  async function reinvite(member) {
    const pin = await pinDialog(t('Enter your PIN'));
    if (pin == null) return;
    const res = await call('/api/sharing/members/invitation', { pin, mailbox_id: member.mailbox_id });
    if (res) {
      invitation = { code: res.code, player: member.player };
      message = t('Give this code to {name}. It works once and for 7 days.', { name: shownName(member.player) });
    }
  }

  async function removeMember(member) {
    if (!await confirmDialog(t('Remove {name} as a member? The mailbox is deleted at once; what the devices already have stays with them.', { name: shownName(member.player) }))) return;
    const pin = await pinDialog(t('Enter your PIN'));
    if (pin == null) return;
    if (await call('/api/sharing/members/remove', { pin, mailbox_id: member.mailbox_id }, t('Member removed.'))) {
      if (invitation?.player === member.player) invitation = null;
    }
    await load();
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(invitation.code);
      message = t('Copied.');
    } catch {
      message = t('Select the code and copy it.');
    }
  }

  async function check() {
    preview = null;
    const res = await call('/api/sharing/preview', { code: joinCode });
    if (!res) return;
    preview = res;
    joinPlayer = res.suggested || NEW;                    // only a player of the same name is suggested, the user confirms
    newPlayer = res.suggested ? '' : res.member;
    direction = 'pull';
    if (res.known) error = t('you are a member of this location already');
  }

  async function join() {
    const name = joinPlayer === NEW ? storedName(newPlayer) : joinPlayer;
    if (!name) return;
    const res = await call('/api/sharing/join', { code: joinCode, player: name, direction },
      t('You are a member of {name}.', { name: preview.location.name }));
    if (res) { joinCode = ''; preview = null; }
    await load();
  }

  async function leave(sub) {
    if (!await confirmDialog(t('Stop being a member of {name}? This installation stops syncing there; what it already has stays.', { name: sub.location_name }))) return;
    await call('/api/sharing/leave', { mailbox_id: sub.mailbox_id }, t('Left.'));
    await load();
  }

  const DIRECTIONS = { pull: t('Receive my matches played there'), push: t('Send my matches to it'), both: t('Both') };
  const noEnter = (e) => { if (e.key === 'Enter') e.preventDefault(); };

  onMount(load);
</script>

{#if sharing?.available}
  <div class="section">
    <div class="title">{t('Sharing')}</div>

    <div class="part first">
      <div class="title sub">{t('Members of this location')}</div>
      {#if !isAdmin}
        <p class="note">{t('Register this installation as a location with a PIN first, then you can invite players.')}</p>
      {:else}
        <div class="row wide">
          <select bind:value={invitePlayer} aria-label={t('Player')}>
            <option value="">{t('Player')}</option>
            {#each candidates as name (name)}<option value={name}>{shownName(name)}</option>{/each}
          </select>
          <button type="button" class="btn" disabled={busy || !invitePlayer} onclick={invite}>{t('Invite player')}</button>
        </div>
        {#if invitation}
          <div class="row wide code-row"><input type="text" class="code" readonly value={invitation.code} aria-label={t('Invitation code')} onfocus={(e) => e.currentTarget.select()}><button type="button" class="btn" onclick={copy}>{t('Copy')}</button></div>
        {/if}
        {#each sharing.members as member (member.mailbox_id)}
          <div class="link">
            <span>{shownName(member.player)}</span>
            <span class="buttons">
              <button type="button" class="btn small" disabled={busy} onclick={() => reinvite(member)}>{t('New invitation')}</button>
              <button type="button" class="btn small" disabled={busy} onclick={() => removeMember(member)}>{t('Remove')}</button>
            </span>
          </div>
        {:else}
          <p class="note">{t('No members yet.')}</p>
        {/each}
      {/if}
    </div>

    <div class="part">
      <div class="title sub">{t('Join a location')}</div>
      <div class="row wide"><input type="text" autocomplete="off" placeholder="BFM1-…" aria-label={t('Invitation')} bind:value={joinCode} onkeydown={noEnter}><button type="button" class="btn" disabled={busy || !joinCode.trim()} onclick={check}>{t('Check')}</button></div>
      {#if preview && !preview.known}
        <p class="note">{t('{location} invites you as {member}. Which player of this installation are you there?', { location: preview.location.name, member: shownName(preview.member) })}</p>
        <div class="row">
          <label for="joinPlayer">{t('Player')}</label>
          <select id="joinPlayer" bind:value={joinPlayer}>
            {#each $players.known as name (name)}<option value={name}>{shownName(name)}{name === preview.suggested ? ' · ' + t('same name') : ''}</option>{/each}
            <option value={NEW}>{t('A new player…')}</option>
          </select>
        </div>
        {#if joinPlayer === NEW}
          <div class="row"><label for="joinNew">{t('Name')}</label><input type="text" id="joinNew" autocomplete="off" maxlength="24" bind:value={newPlayer} onkeydown={noEnter}></div>
        {/if}
        <div class="row">
          <label for="joinDirection">{t('Direction')}</label>
          <select id="joinDirection" bind:value={direction}>
            {#each Object.entries(DIRECTIONS) as [value, label] (value)}<option {value}>{label}</option>{/each}
          </select>
        </div>
        <button type="button" class="btn" disabled={busy || (joinPlayer === NEW && !storedName(newPlayer))} onclick={join}>{t('Join')}</button>
      {/if}
    </div>

    <div class="part">
      <div class="title sub">{t('Memberships')}</div>
      {#each sharing.subscriptions as sub (sub.mailbox_id)}
        <div class="link">
          <span>{sub.location_name} · {shownName(sub.player)} · {DIRECTIONS[sub.direction]}</span>
          <button type="button" class="btn small" disabled={busy} onclick={() => leave(sub)}>{t('Leave')}</button>
        </div>
      {:else}
        <p class="note">{t('You are not a member of a location.')}</p>
      {/each}
    </div>

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
  .title.sub { margin: 0 0 0.75rem; }
  .part { border-top: 1px solid var(--glass-border); padding-top: 1rem; margin-top: 1rem; }
  .part.first { border-top: none; padding-top: 0; margin-top: 0; }
  .buttons { display: flex; flex-wrap: wrap; gap: 0.5rem; }
  .code-row { margin-top: 0.75rem; margin-bottom: 0.5rem; }
  .row { display: grid; grid-template-columns: 8rem 1fr; align-items: center; gap: 0.5rem; margin-bottom: 0.65rem; }
  .row label { font-size: 0.9rem; color: color-mix(in srgb, var(--text) 72%, transparent); }
  .row input, .row select {
    width: 100%; background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border);
    border-radius: 10px; color: var(--text); padding: 0.45rem 0.75rem; font-size: 0.9rem; font-family: inherit;
  }
  .row input:focus, .row select:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 25%, transparent); }
  .row.wide { grid-template-columns: 1fr auto; }
  .row input.code { font-family: monospace; font-size: 0.8rem; }
  .link { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; margin-bottom: 0.5rem; font-size: 0.9rem; }
  .note { font-size: 0.75rem; color: var(--muted); margin: 0 0 0.5rem; }
  .note.error { color: var(--red); }
  .btn { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 8px; padding: 0.5rem 1rem; font-size: 0.9rem; font-weight: 600; font-family: inherit; cursor: pointer; transition: opacity 0.15s; }
  .btn.small { padding: 0.25rem 0.7rem; font-size: 0.8rem; text-transform: none; letter-spacing: 0; }
  .btn:hover { opacity: 0.85; }
  .btn:disabled { opacity: 0.4; cursor: default; }
  @media (max-width: 520px) {
    .row { grid-template-columns: 1fr; }
  }
</style>
