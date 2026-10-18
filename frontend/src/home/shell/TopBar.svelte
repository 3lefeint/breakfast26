<script>
  import { openTv } from '../../lib/router.js';
  import { t } from '../../lib/i18n.js';
  // The bar above the pages of the Home app: the connections (board, MQTT, Autodarts, and the live
  // connection to this app while it is down), a button that opens the TV view and a shortcut to
  // Settings. It spans the whole width, the brand sits at its left. The TV view uses the same bar
  // (`tv`): without the button that opens it, with the title of the running game in the middle, a
  // `right` snippet for its controls and `glowColor` ('green' | 'yellow' | 'red') for the board status.
  import Icon from '../../lib/components/Icon.svelte';
  import logo from '../../lib/assets/logo.png';

  let { boardConnected = false, mqttOk = null, autodartsOk = false, wsConnected = true, connLabel = '', tv = false, title = '', glowColor = null, right: rightSlot, titleExtra } = $props();
</script>

<header class="topbar" class:glow-green={glowColor === 'green'} class:glow-yellow={glowColor === 'yellow'} class:glow-red={glowColor === 'red'}>
  <a class="brand" href="#home" title={t('Breakfast')}>
    <img class="mark" src={logo} alt="" width="56" height="56">
    <span class="word">{t('Breakfast')}</span>
  </a>
  <div class="title">{title}{@render titleExtra?.()}</div>
  <div class="right">
    <span class="statuses">
      {#if !wsConnected}
        <span class="status"><span class="dot"></span><span class="label">{connLabel}</span></span>
      {/if}
      <span class="status" title={boardConnected ? t('Board connected') : t('Board offline')}><span class="dot" class:ok={boardConnected}></span><span class="label">{boardConnected ? t('Board connected') : t('Board offline')}</span></span>
      {#if mqttOk !== null}
        <span class="status" title={t('MQTT')}><span class="dot" class:ok={mqttOk}></span><span class="label">{t('MQTT')}</span></span>
      {/if}
      <span class="status" title={t('Autodarts')}><span class="dot" class:ok={autodartsOk}></span><span class="label">{t('Autodarts')}</span></span>
    </span>
    {@render rightSlot?.()}
    {#if !tv}
      <a class="btn tv" href="#tv" onclick={openTv}><Icon name="tv" size={20} /><span>{t('Open TV')}</span></a>
    {/if}
    <a class="btn icon" href="#settings" aria-label={t('Settings')} title={t('Settings')}><Icon name="settings" size={20} /></a>
  </div>
</header>

<style>
  .topbar {
    position: sticky; top: 0; z-index: 40; height: var(--header-h, 4.1rem); flex-shrink: 0;
    grid-column: 1 / -1; grid-row: 1;
    display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 1rem; padding: 0 1.5rem 0 1.5rem;
    background: var(--glass-bar); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur);
    border-bottom: 1px solid var(--glass-border); box-shadow: var(--glass-bar-shadow);
  }
  .topbar.glow-green { box-shadow: 0 2px 0 0 var(--green), 0 10px 28px -6px color-mix(in srgb, var(--green) 65%, transparent); }
  .topbar.glow-yellow { box-shadow: 0 2px 0 0 var(--yellow), 0 10px 28px -6px color-mix(in srgb, var(--yellow) 65%, transparent); }
  .topbar.glow-red { box-shadow: 0 2px 0 0 var(--red), 0 10px 28px -6px color-mix(in srgb, var(--red) 65%, transparent); }
  .title { justify-self: center; text-align: center; font-weight: 700; font-size: 1.05rem; white-space: nowrap; display: flex; align-items: center; gap: 0.8rem; }
  .brand { display: flex; align-items: center; gap: 0.7rem; justify-self: start; color: var(--text); text-decoration: none; }
  .mark { display: block; width: 56px; height: 56px; margin: -6px -4px -6px -8px; }
  .word { font-size: 1.45rem; font-weight: 800; letter-spacing: -0.02em; }
  .right { display: flex; align-items: center; gap: 0.8rem; justify-self: end; }
  .statuses { display: flex; align-items: center; gap: 1.1rem; margin-right: 0.4rem; }
  .status { display: flex; align-items: center; gap: 0.55rem; font-size: 0.9rem; color: var(--text); }
  .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--red); box-shadow: 0 0 10px var(--red); transition: background 0.3s; }
  .dot.ok { background: var(--green); box-shadow: 0 0 10px var(--green); }
  .btn {
    display: inline-flex; align-items: center; gap: 0.55rem; height: 2.75rem; padding: 0 1.1rem;
    border: 1px solid var(--glass-border); border-radius: 10px; color: var(--text); text-decoration: none;
    background: var(--glass); font-size: 0.95rem; transition: border-color 0.15s, background 0.15s;
  }
  .btn:hover { border-color: var(--accent); background: var(--glass-strong); }
  .btn.icon { width: 2.75rem; padding: 0; justify-content: center; }

  @media (max-width: 800px) {
    .topbar { padding: 0 1rem; }
    .statuses { gap: 0.6rem; margin-right: 0; }
    .status .label { display: none; }
    .btn.tv span { display: none; }
    .btn.tv { width: 2.75rem; padding: 0; justify-content: center; }
  }
</style>
