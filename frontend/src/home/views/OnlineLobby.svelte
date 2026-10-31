<script>
  import { t } from '../../lib/i18n.js';
  // Online Elimination on Home: host a match, join one of a linked location or join with a code, pick the players
  // of this site and (as the host) order them and start. Once the match runs, the TV view takes over.
  // The open matches of the linked locations are fetched when the page opens and on Refresh, not kept up to date.
  import { onMount, untrack } from 'svelte';
  import { online } from '../../lib/stores/online.js';
  import { players } from '../../lib/stores/players.js';
  import { apiJson } from '../../lib/api.js';
  import { shownName } from '../../lib/util.js';
  import VoiceButton from '../../lib/components/VoiceButton.svelte';
  import Toggle from '../../lib/components/Toggle.svelte';
  import OnlineX01Rules from './OnlineX01Rules.svelte';

  // Which game this page hosts: the Elimination page or the X01 page. A site that joins sees the game of the host.
  let { game = 'elimination' } = $props();

  let configured = $state(true);
  let site = $state('');
  let locationName = $state('');
  let password = $state('');
  let joinPassword = $state('');
  let code = $state('');
  let open = $state({ registered: false, matches: [], error: '' });
  let error = $state('');
  let busy = $state(false);

  let lives = $state(3);
  let order = $state([]);
  let randomOrder = $state(true);       // drawn when the host starts, so nobody sees an order before
  let rules = $state({ start: 501, in_mode: 'straight', out_mode: 'double', legs: 1, bull_off: true, max_rounds: null });

  onMount(async () => {
    if (game === 'x01') randomOrder = false;        // the bull-off is on at first: it draws the order of the throws
    const res = await fetch('/api/online').then((r) => r.json()).catch(() => null);
    if (res) {
      configured = res.configured;
      site = res.site_name || '';
      locationName = res.location_name || '';
    }
    loadOpen();
  });

  async function loadOpen() {
    const res = await apiJson('GET', '/api/online/open').catch(() => null);
    if (!res) return;
    open = res.error ? { registered: true, matches: [], error: res.error } : { registered: res.registered, matches: res.matches, error: '' };
  }

  // Back on the start page after a match: the list may have changed.
  let wasOnline = false;
  $effect(() => {
    const now = !!$online;
    if (!now && wasOnline) untrack(loadOpen);
    wasOnline = now;
  });

  // A name another site already uses is the one error that needs more than the relay's words.
  const explain = (message) => /site name is already taken/.test(message)
    ? t('That site name is already taken in this match. Enter another name for this site.') : t(message);

  async function run(url, body) {
    busy = true;
    error = '';
    const res = await apiJson('POST', url, body);
    busy = false;
    if (res.error) error = explain(res.error);
    return res;
  }

  const create = () => run('/api/online/create', { site, password });
  const join = () => run('/api/online/join', { code, site, password: joinPassword, game });
  const joinLinked = (match) => run('/api/online/join-linked', { code: match.code, site, game });
  // A match of the other game is joined on the page of that game.
  let openHere = $derived(open.matches.filter((m) => (m.game ?? 'elimination') === game));
  const leave = () => run('/api/online/leave');

  let mine = $derived($online?.lobby.sites.find((s) => s.site === $online.site)?.players ?? []);
  let everyone = $derived(($online?.lobby.sites ?? []).flatMap((s) => s.players));

  // The host's order: keep what was arranged, drop who left, add who came.
  $effect(() => {
    const kept = order.filter((p) => everyone.includes(p));
    const added = everyone.filter((p) => !kept.includes(p));
    if (kept.length !== order.length || added.length) order = [...kept, ...added];
  });

  // After a rematch the relay proposes the order of a local rematch and the lives of the last match.
  let proposed = '';
  $effect(() => {
    const lobby = $online?.lobby;
    if (!lobby?.order.length) return;
    const key = JSON.stringify([lobby.order, lobby.lives]);
    if (key === proposed) return;
    proposed = key;
    order = lobby.order.filter((p) => everyone.includes(p));
    randomOrder = false;        // the order of a rematch comes from the rules of the game
    if (lobby.lives) lives = lobby.lives;
    if (lobby.game === 'x01' && lobby.rules) rules = { ...lobby.rules, bull_off: false };       // a rematch has no new bull-off
  });

  function toggle(name) {
    const next = mine.includes(name) ? mine.filter((p) => p !== name) : [...mine, name];
    run('/api/online/players', { players: next });
  }
  function move(i, dir) {
    const j = i + dir;
    if (j < 0 || j >= order.length) return;
    [order[i], order[j]] = [order[j], order[i]];
  }
  function shuffled(arr) {
    const a = arr.slice();
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }
  // X01: the game of the lobby and whether the order of the players is drawn when the match starts (always with a bull-off).
  let isX01 = $derived((($online?.host || !$online) ? game : ($online.lobby.game ?? game)) === 'x01');
  let drawn = $derived(randomOrder || (isX01 && rules.bull_off));
  const onBullOff = (on) => { if (on) randomOrder = false; };
  const onRandom = (on) => { if (on && isX01) rules.bull_off = false; };

  // The host shows the other sites the game and its rules while they are in the lobby, once for every change: the relay
  // answers each one with a lobby frame, which must not start the next one.
  let pushed = '';
  $effect(() => {
    if ($online?.phase !== 'lobby' || !$online.host) { pushed = ''; return; }
    const body = isX01 ? { game: 'x01', rules: { ...rules } } : { game: 'elimination', lives };
    const key = JSON.stringify(body);
    untrack(() => {
      if (key === pushed) return;
      pushed = key;
      apiJson('POST', '/api/online/rules', body).catch(() => null);
    });
  });

  const start = () => run('/api/online/start', {
    ...(isX01 ? { game: 'x01', rules: { ...rules } } : { lives }), order: drawn ? shuffled(order) : order });
  const ownerOf = (name) => $online.lobby.sites.find((s) => s.players.includes(name))?.site;
</script>

<div class="elim-section">
  <div class="elim-section-title">{t('Online match')}</div>

  {#if !$online}
    {#if !configured}
      <p class="note">{t('Set the relay address under Settings → Online first.')}</p>
    {:else}
      <div class="form">
        <label>{t('This site\'s name')} <input type="text" bind:value={site} placeholder={locationName || t('e.g. Home')} maxlength="24"></label>
      </div>
      {#if open.registered}
        <div class="box open-box">
          <div class="box-title">{t('Matches of linked locations')} <button type="button" class="btn-link" onclick={loadOpen}>{t('Refresh')}</button></div>
          {#each openHere as m (m.code)}
            <div class="open-match">
              <span><strong>{m.location.name}</strong> <span class="hint">· {t('{players} players', { players: m.players })}</span></span>
              <button class="btn btn-start" disabled={busy || !(site.trim() || locationName)} onclick={() => joinLinked(m)}>{t('Join')}</button>
            </div>
          {:else}
            <p class="note">{open.error || t('No open matches.')}</p>
          {/each}
        </div>
      {/if}
      <div class="two">
        <div class="box">
          <div class="box-title">{t('Host a match')}</div>
          <input type="text" bind:value={password} placeholder={t('Password (optional)')} title={t('Without a password only linked locations can join')}>
          <button class="btn btn-start" disabled={busy || !(site.trim() || locationName)} onclick={create}>{t('Create')}</button>
        </div>
        <div class="box">
          <div class="box-title">{t('Join with a code')}</div>
          <input type="text" class="code-input" bind:value={code} placeholder={t('CODE')} maxlength="6">
          <input type="text" bind:value={joinPassword} placeholder={t('Match password')}>
          <button class="btn btn-add" disabled={busy || !(site.trim() || locationName) || !joinPassword || code.trim().length < 6} onclick={join}>{t('Join')}</button>
        </div>
      </div>
    {/if}

  {:else if $online.phase === 'connecting'}
    <p class="note">{t('Connecting to the relay…')}</p>

  {:else if $online.phase === 'lobby'}
    <div class="head">
      <div class="code-row">
        <span class="code">{$online.code}</span>
        <span class="code-text"><span class="label">{t('Join code')}</span><span class="hint">{t('valid for 10 minutes')}</span></span>
      </div>
      <div class="head-actions">
        {#if $online.host}
          <button class="btn btn-start" disabled={busy || order.length < 2} onclick={start}>{t('▶ Start')}</button>
        {/if}
        <VoiceButton>
          {#snippet trigger(open)}<button class="btn btn-add emoji" title={t('Opens in a new tab. Keep it open while you play.')} aria-label={t('Voice chat')} onclick={open}>🎧</button>{/snippet}
        </VoiceButton>
      </div>
    </div>

    <div class="sites">
      {#each $online.lobby.sites as s (s.site)}
        <div class="site" class:me={s.site === $online.site}>
          <span class="dot" class:ok={s.connected}></span>
          <strong>{s.site}</strong>
          {#if s.site === $online.lobby.host}<span class="tag">{t('host')}</span>{/if}
          {#if s.site === $online.site}<span class="tag">{t('you')}</span>{/if}
          <span class="site-players">{s.players.length ? s.players.map(shownName).join(', ') : t('no players yet')}</span>
        </div>
      {/each}
    </div>

    <div class="top">
      <div class="left">
        {#if $online.host}
          {#if isX01}
            <OnlineX01Rules bind:rules onbulloff={onBullOff} />
          {:else}
            <div class="option-row">
              <span class="label">{t('Lives per player')}</span>
              <div class="counter">
                <button class="btn-counter" onclick={() => (lives = Math.max(1, lives - 1))}>−</button>
                <span class="counter-val">{lives}</span>
                <button class="btn-counter" onclick={() => (lives = Math.min(10, lives + 1))}>+</button>
              </div>
            </div>
          {/if}
          <Toggle bind:checked={randomOrder} label={t('Random order')} onchange={onRandom} />
        {:else if $online.lobby.game === 'x01' && $online.lobby.rules}
          <OnlineX01Rules rules={$online.lobby.rules} editable={false} />
        {/if}

        <div class="elim-section-title">{t('Choose Players')}</div>
        <div class="known-chips">
          {#each $players.known as name (name)}
            <button type="button" class="chip" class:in-game={mine.includes(name)} disabled={everyone.includes(name) && !mine.includes(name)}
                    onclick={() => toggle(name)}>{shownName(name)}{#if everyone.includes(name) && !mine.includes(name)} <span class="hint">· {ownerOf(name)}</span>{/if}</button>
          {/each}
        </div>
      </div>

      <!-- The same word in both languages, like on the setup pages of the local games. -->
      <div class="right">
        <div class="elim-section-title">Players</div>
        <ul class="order">
          {#if $online.host && !drawn}
            {#each order as name, i (name)}
              <li>
                <span class="num">{i + 1}</span>
                <span class="player-name-text">{shownName(name)} <span class="hint">· {ownerOf(name)}</span></span>
                <button class="btn-icon" onclick={() => move(i, -1)} disabled={i === 0}>↑</button>
                <button class="btn-icon" onclick={() => move(i, +1)} disabled={i === order.length - 1}>↓</button>
              </li>
            {/each}
          {:else}
            {#each ($online.host ? order : everyone) as name (name)}
              <li><span class="player-name-text">{shownName(name)} <span class="hint">· {ownerOf(name)}</span></span></li>
            {/each}
          {/if}
        </ul>
      </div>
    </div>

    {#if !$online.host}
      <p class="note">{t('Waiting for the host to start the match…')}</p>
    {/if}
    <div class="foot"><button class="btn-link" onclick={leave}>{t('Leave')}</button></div>

  {:else if $online.phase === 'ended'}
    {#if $online.result?.placements?.length}
      <ol class="result">
        {#each $online.result.placements as p}<li>{shownName(p.player)}</li>{/each}
      </ol>
    {:else}
      <p class="note">{t('The match ended without a result.')}</p>
    {/if}
    <button class="btn btn-start" onclick={leave}>{t('Close')}</button>
  {/if}

  {#if error || $online?.message}<p class="error">{error || $online.message}</p>{/if}
</div>

<style>
  .elim-section { background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); border-radius: 16px; padding: 1.25rem; margin-bottom: 1rem; }
  .elim-section-title { font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; margin: 1rem 0 0.75rem; }
  .elim-section-title:first-child { margin-top: 0; }
  .hint { color: var(--muted); font-size: 0.75rem; text-transform: none; letter-spacing: normal; font-weight: 400; }
  .note { color: var(--muted); font-size: 0.9rem; margin: 0.75rem 0; }
  .error { color: var(--red); font-size: 0.85rem; margin-top: 0.75rem; }
  .form { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; margin-bottom: 1rem; }
  .form label { display: flex; flex-direction: column; gap: 0.3rem; font-size: 0.8rem; color: var(--muted); }
  input[type='text'] { background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); color: var(--text); border-radius: 12px; padding: 0.5rem 0.7rem; font-size: 0.9rem; font-family: inherit; }
  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; }
  .box { background: rgba(0, 0, 0, 0.22); border: 1px solid var(--glass-border); border-radius: 10px; padding: 0.9rem; display: flex; flex-direction: column; gap: 0.6rem; align-items: flex-start; }
  .box-title { font-size: 0.85rem; font-weight: 600; }
  .open-box { margin-bottom: 0.75rem; align-items: stretch; }
  .open-match { display: flex; align-items: center; justify-content: space-between; gap: 0.75rem; }
  .head { display: flex; align-items: center; justify-content: space-between; gap: 1rem; margin-bottom: 1rem; flex-wrap: wrap; }
  .head-actions { display: flex; align-items: center; gap: 0.6rem; }
  .head-actions .btn { height: 2.6rem; box-sizing: border-box; padding-top: 0; padding-bottom: 0; }
  .head-actions .emoji { width: 2.6rem; padding: 0; font-size: 1.15rem; line-height: 1; }
  .foot { display: flex; justify-content: flex-end; }
  .code-input { text-transform: uppercase; letter-spacing: 0.25em; font-family: monospace; width: 10rem; }
  .code-row { display: flex; align-items: center; gap: 0.9rem; flex-wrap: wrap; }
  .code-text { display: flex; flex-direction: column; gap: 0.1rem; }
  .code-text .label { color: var(--muted); font-size: 0.85rem; }
  .code { font-family: monospace; font-size: 2rem; font-weight: 800; letter-spacing: 0.3em; color: var(--accent); }
  .sites { display: flex; flex-direction: column; gap: 0.4rem; margin-bottom: 0.5rem; }
  .site { display: flex; align-items: center; gap: 0.5rem; padding: 0.5rem 0.7rem; background: rgba(0, 0, 0, 0.22); border: 1px solid var(--glass-border); border-radius: 8px; font-size: 0.9rem; }
  .site.me { border-color: var(--accent); }
  .site-players { margin-left: auto; color: var(--muted); font-size: 0.85rem; }
  .tag { font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); border: 1px solid var(--glass-border); border-radius: 4px; padding: 0 0.3rem; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--red); }
  .dot.ok { background: var(--green); }
  .known-chips { display: flex; flex-wrap: wrap; gap: 0.4rem; }
  .chip { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 20px; padding: 0.3rem 0.7rem; font-family: inherit; font-size: 0.85rem; cursor: pointer; }
  .chip:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
  .chip.in-game { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
  .chip:disabled { opacity: 0.4; cursor: not-allowed; }
  .order { list-style: none; padding: 0; margin-bottom: 0.75rem; }
  .order li { display: flex; align-items: center; gap: 0.5rem; padding: 0.4rem 0; border-bottom: 1px solid var(--glass-border); }
  .order .num { width: 1.4rem; color: var(--muted); font-size: 0.8rem; }
  .player-name-text { flex: 1; font-size: 0.95rem; }
  .btn-icon { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 6px; color: var(--muted); cursor: pointer; padding: 0.2rem 0.45rem; font-size: 0.8rem; }
  .btn-icon:disabled { opacity: 0.3; cursor: default; }
  .top { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 1.5rem; align-items: start; margin-bottom: 1.2rem; }
  .right .elim-section-title { margin-top: 0; }
  .option-row { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.8rem; flex-wrap: wrap; }
  .option-row .label { font-size: 0.9rem; color: var(--muted); min-width: 8rem; }
  @media (max-width: 900px) { .top { grid-template-columns: 1fr; } }
  .counter { display: flex; align-items: center; gap: 0.5rem; }
  .counter-val { font-size: 1.3rem; font-weight: 700; min-width: 2rem; text-align: center; }
  .btn-counter { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 10px; width: 2rem; height: 2rem; cursor: pointer; font-size: 1.1rem; }
  .btn { border: none; border-radius: 8px; padding: 0.65rem 1.5rem; font-size: 0.95rem; font-weight: 600; cursor: pointer; transition: opacity 0.15s; font-family: inherit; }
  .btn:hover { opacity: 0.85; }
  .btn:disabled { opacity: 0.4; cursor: default; }
  .btn-start { background: #166534; color: #fff; }
  .btn-add { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); }
  .btn-link { background: none; border: none; color: var(--muted); cursor: pointer; margin-left: 0.5rem; font: inherit; text-decoration: underline; }
  .result { padding-left: 1.5rem; margin-bottom: 1rem; }
  @media (max-width: 640px) { .form, .two { grid-template-columns: 1fr; } }
</style>
