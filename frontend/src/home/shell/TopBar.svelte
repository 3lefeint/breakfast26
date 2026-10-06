<script>
  import { t } from '../../lib/i18n.js';
  // The bar above the pages of the Home app: whether the board is connected, a button that opens the
  // TV view and a shortcut to Settings. It spans the whole width, the brand sits at its left.
  import Icon from '../../lib/components/Icon.svelte';
  import logo from '../../lib/assets/logo.png';

  let { boardConnected = false } = $props();
</script>

<header class="topbar">
  <a class="brand" href="#home" title={t('Breakfast')}>
    <img class="mark" src={logo} alt="" width="56" height="56">
    <span class="word">{t('Breakfast')}</span>
  </a>
  <div class="right">
    <span class="status"><span class="dot" class:ok={boardConnected}></span>{boardConnected ? t('Board connected') : t('Board offline')}</span>
    <a class="btn tv" href="/tv"><Icon name="tv" size={20} /><span>{t('Open TV')}</span></a>
    <a class="btn icon" href="#settings" aria-label={t('Settings')} title={t('Settings')}><Icon name="settings" size={20} /></a>
  </div>
</header>

<style>
  .topbar {
    position: sticky; top: 0; z-index: 40; height: var(--header-h); flex-shrink: 0;
    grid-column: 1 / -1; grid-row: 1;
    display: flex; align-items: center; justify-content: flex-end; gap: 1rem; padding: 0 1.5rem 0 1.5rem;
    background: var(--glass); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur);
    border-bottom: 1px solid var(--glass-border); box-shadow: var(--glass-bar-shadow);
  }
  .brand { display: flex; align-items: center; gap: 0.7rem; margin-right: auto; color: var(--text); text-decoration: none; }
  .mark { display: block; width: 56px; height: 56px; margin: -6px -4px -6px -8px; }
  .word { font-size: 1.45rem; font-weight: 800; letter-spacing: -0.02em; }
  .right { display: flex; align-items: center; gap: 0.8rem; }
  .status { display: flex; align-items: center; gap: 0.55rem; font-size: 0.9rem; color: var(--text); margin-right: 0.4rem; }
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
    .status { display: none; }
    .btn.tv span { display: none; }
    .btn.tv { width: 2.75rem; padding: 0; justify-content: center; }
  }
</style>
