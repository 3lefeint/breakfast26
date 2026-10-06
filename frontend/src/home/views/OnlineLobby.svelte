<script>
  import { t } from '../../lib/i18n.js';
  // Online Elimination on Home: host a match or join one with a code, pick the players of this
  // site, and (as the host) order them and start. Once the match runs, /tv takes over.
  import { onMount } from 'svelte';
  import { online } from '../../lib/stores/online.js';
  import { players } from '../../lib/stores/players.js';
  import { apiJson } from '../../lib/api.js';
  import { cap } from '../../lib/util.js';

  let configured = $state(true);
  let site = $state('');
  let password = $state('');
  let code = $state('');
  let error = $state('');
  let busy = $state(false);

  let lives = $state(3);
  let order = $state([]);

  onMount(async () => {
    const res = await fetch('/api/online').then((r) => r.json()).catch(() => null);
    if (res) {
      configured = res.configured;
      site = res.site_name || '';
    }
  });

  async function run(url, body) {
    busy = true;
    error = '';
    const res = await apiJson('POST', url, body);
    busy = false;
    if (res.error) error = t(res.error);
    return res;
  }

  const create = () => run('/api/online/create', { site, password });
  const join = () => run('/api/online/join', { code, site, password });
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
    if (lobby.lives) lives = lobby.lives;
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
  function shuffle() {
    const a = order.slice();
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    order = a;
  }
  const start = () => run('/api/online/start', { lives, order });
  const ownerOf = (name) => $online.lobby.sites.find((s) => s.players.includes(name))?.site;
</script>

<div class="elim-section">
  <div class="elim-section-title">{t('Online match')}</div>

  {#if !$online}
    {#if !configured}
      <p class="note">{t('Set the relay address under Settings → Online first.')}</p>
    {:else}
      <div class="form">
        <label>{t('This site\'s name')} <input type="text" bind:value={site} placeholder={t('e.g. Home')} maxlength="24"></label>
        <label>{t('Match password')} <input type="text" bind:value={password} placeholder={t('everyone needs the same one')}></label>
      </div>
      <div class="two">
        <div class="box">
          <div class="box-title">{t('Host a match')}</div>
          <button class="btn btn-start" disabled={busy || !site.trim() || !password} onclick={create}>{t('Create')}</button>
        </div>
        <div class="box">
          <div class="box-title">{t('Join with a code')}</div>
          <input type="text" class="code-input" bind:value={code} placeholder={t('CODE')} maxlength="6">
          <button class="btn btn-add" disabled={busy || !site.trim() || !password || code.trim().length < 6} onclick={join}>{t('Join')}</button>
        </div>
      </div>
    {/if}

  {:else if $online.phase === 'connecting'}
    <p class="note">{t('Connecting to the relay…')}</p>

  {:else if $online.phase === 'lobby'}
    <div class="code-row">
      <span class="label">{t('Join code')}</span>
      <span class="code">{$online.code}</span>
      <span class="hint">{t('valid for 10 minutes, with the match password')}</span>
    </div>

    <div class="sites">
      {#each $online.lobby.sites as s (s.site)}
        <div class="site" class:me={s.site === $online.site}>
          <span class="dot" class:ok={s.connected}></span>
          <strong>{s.site}</strong>
          {#if s.site === $online.lobby.host}<span class="tag">{t('host')}</span>{/if}
          {#if s.site === $online.site}<span class="tag">{t('you')}</span>{/if}
          <span class="site-players">{s.players.length ? s.players.map(cap).join(', ') : t('no players yet')}</span>
        </div>
      {/each}
    </div>

    <div class="elim-section-title">{t('Your players')} <span class="hint">{t('(click to add or remove)')}</span></div>
    <div class="known-chips">
      {#each $players.known as name (name)}
        <button type="button" class="chip" class:in-game={mine.includes(name)} disabled={everyone.includes(name) && !mine.includes(name)}
                onclick={() => toggle(name)}>{cap(name)}</button>
      {/each}
    </div>

    {#if $online.host}
      <div class="elim-section-title">{t('Order')} <span class="hint">{t('(order = play order)')}</span></div>
      <ul class="order">
        {#each order as name, i (name)}
          <li>
            <span class="num">{i + 1}</span>
            <span class="player-name-text">{cap(name)} <span class="hint">· {ownerOf(name)}</span></span>
            <button class="btn-icon" onclick={() => move(i, -1)} disabled={i === 0}>↑</button>
            <button class="btn-icon" onclick={() => move(i, +1)} disabled={i === order.length - 1}>↓</button>
          </li>
        {/each}
      </ul>
      <div class="lives-row">
        <span class="label">{t('Lives per player')}</span>
        <div class="counter">
          <button class="btn-counter" onclick={() => (lives = Math.max(1, lives - 1))}>−</button>
          <span class="counter-val">{lives}</span>
          <button class="btn-counter" onclick={() => (lives = Math.min(10, lives + 1))}>+</button>
        </div>
        <button class="btn btn-add" onclick={shuffle} disabled={order.length < 2}>{t('🔀 Shuffle')}</button>
      </div>
      <button class="btn btn-start" disabled={busy || order.length < 2} onclick={start}>{t('▶ Start')}</button>
    {:else}
      <p class="note">{t('Waiting for the host to start the match…')}</p>
    {/if}
    <button class="btn-link" onclick={leave}>{t('Leave')}</button>

  {:else if $online.phase === 'ended'}
    {#if $online.result?.placements?.length}
      <ol class="result">
        {#each $online.result.placements as p}<li>{cap(p.player)}</li>{/each}
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
  .code-input { text-transform: uppercase; letter-spacing: 0.25em; font-family: monospace; width: 10rem; }
  .code-row { display: flex; align-items: baseline; gap: 0.75rem; margin-bottom: 1rem; flex-wrap: wrap; }
  .code-row .label { color: var(--muted); font-size: 0.85rem; }
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
  .lives-row { display: flex; align-items: center; gap: 0.75rem; margin: 0.75rem 0 1rem; flex-wrap: wrap; }
  .lives-row .label { font-size: 0.9rem; color: var(--muted); }
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
