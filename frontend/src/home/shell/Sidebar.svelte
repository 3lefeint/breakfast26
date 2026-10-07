<script>
  import { t } from '../../lib/i18n.js';
  // The navigation of the Home app: the four main places and Settings at the bottom, below them the
  // version (five taps in a row unlock the Dev tab) and the link to the About page. The panel is as
  // tall as the page, its content stays in view. On narrow screens it becomes a bar along the bottom
  // edge. Board opens the board manager of the installation and is disabled when none is configured.
  import Icon from '../../lib/components/Icon.svelte';

  let { route, boardAddress = null, version = '', onVersionTap = () => {} } = $props();

  const PLAY_ROUTES = ['', 'home', 'elimination', 'target-battle', 'killer', 'field-training', 'black-belt', 'checkout-trainer', 'checkout-training', 'checkout-quiz', 'setup-shots'];

  let items = $derived([
    { id: 'play', label: t('Play'), icon: 'play', href: '#home', active: PLAY_ROUTES.includes(route) },
    { id: 'players', label: t('Players'), icon: 'players', href: '#players', active: route === 'players' || route.startsWith('profile/') },
    { id: 'stats', label: t('Stats'), icon: 'stats', href: '#stats', active: route === 'stats' },
    { id: 'board', label: t('Board'), icon: 'board', href: boardAddress, external: true, disabled: !boardAddress },
  ]);
  let settingsActive = $derived(route === 'settings');
</script>

<nav class="sidebar" aria-label={t('Main')}>
 <div class="inner">
  <ul class="items">
    {#each items as item (item.id)}
      <li>
        <a class="item" class:active={item.active} class:disabled={item.disabled}
           href={item.disabled ? undefined : item.href}
           target={item.external ? '_blank' : undefined} rel={item.external ? 'noopener' : undefined}
           aria-current={item.active ? 'page' : undefined}>
          <Icon name={item.icon} size={22} />
          <span>{item.label}</span>
        </a>
      </li>
    {/each}
  </ul>

  <a class="item settings" class:active={settingsActive} href="#settings" aria-current={settingsActive ? 'page' : undefined}>
    <Icon name="settings" size={22} />
    <span>{t('Settings')}</span>
  </a>

  <div class="meta">
    <button type="button" class="version" onclick={onVersionTap}>{version ? `v${version}` : ''}</button>
    <a class="about" href="#about" class:active={route === 'about'} aria-label={t('About')} title={t('About')}><Icon name="info" size={18} /></a>
  </div>
 </div>
</nav>

<style>
  .sidebar {
    width: 240px; flex-shrink: 0; grid-row: 2; grid-column: 1;
    background: var(--glass); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur);
    border-right: 1px solid var(--glass-border); box-shadow: var(--glass-bar-shadow);
    z-index: 30;
  }
  .inner {
    position: sticky; top: var(--header-h); height: calc(100vh - var(--header-h)); box-sizing: border-box;
    display: flex; flex-direction: column; padding: 1rem 0.75rem; overflow-y: auto;
  }
  .items { list-style: none; display: flex; flex-direction: column; gap: 0.3rem; flex: 1; }
  .item {
    display: flex; align-items: center; gap: 0.85rem; padding: 0.7rem 0.9rem;
    border-radius: 10px; border: 1px solid transparent; border-left: 3px solid transparent;
    color: var(--text); text-decoration: none; font-size: 1.1rem;
    transition: background 0.15s, border-color 0.15s, color 0.15s;
  }
  .item :global(svg) { color: var(--muted); transition: color 0.15s; }
  .item:hover { background: var(--glass-strong); }
  .item.active {
    background: color-mix(in srgb, var(--accent) 22%, transparent);
    border-left-color: var(--accent); color: var(--text);
  }
  .item.active :global(svg) { color: var(--accent); }
  .item.disabled { opacity: 0.4; pointer-events: none; }
  .settings { margin-top: auto; }
  .meta { display: flex; align-items: center; justify-content: space-between; padding: 0.9rem 0.9rem 0.1rem; }
  .version { color: var(--muted); font: inherit; font-size: 0.8rem; background: none; border: none; padding: 0; cursor: pointer; user-select: none; }
  .about { color: var(--muted); line-height: 0; }
  .about:hover, .about.active { color: var(--text); }

  @media (max-width: 800px) {
    .sidebar {
      position: fixed; top: auto; bottom: 0; left: 0; right: 0; width: auto; height: calc(var(--nav-h, 4.2rem) + env(safe-area-inset-bottom)); box-sizing: border-box; grid-row: auto; grid-column: auto;
      border-right: none; border-top: 1px solid var(--glass-border);
    }
    .inner {
      position: static; height: 100%; flex-direction: row; align-items: center; padding: 0.35rem 0.5rem calc(0.35rem + env(safe-area-inset-bottom)); overflow: visible;
    }
    .items { flex-direction: row; flex: 1; justify-content: space-around; gap: 0; }
    .item { flex-direction: column; gap: 0.15rem; padding: 0.4rem 0.6rem; font-size: 0.7rem; border-left: none; }
    .item.active { border-left-color: transparent; }
    .settings { margin-top: 0; }
    .meta { padding: 0 0.4rem; gap: 0.5rem; }
    .version { display: none; }
  }
</style>
