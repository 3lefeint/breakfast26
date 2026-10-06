<script>
  import { t } from '../../lib/i18n.js';
  // The navigation of the Home app: the four main places and Settings at the bottom. On
  // narrow screens it becomes a bar along the bottom edge. Board opens the board manager of the
  // installation and is disabled when none is configured.
  import Icon from '../../lib/components/Icon.svelte';

  let { route, boardAddress = null } = $props();

  const PLAY_ROUTES = ['', 'home', 'elimination', 'target-battle', 'killer', 'field-training', 'black-belt'];

  let items = $derived([
    { id: 'play', label: t('Play'), icon: 'play', href: '#home', active: PLAY_ROUTES.includes(route) },
    { id: 'players', label: t('Players'), icon: 'players', href: '#players', active: route === 'players' || route.startsWith('profile/') },
    { id: 'stats', label: t('Stats'), icon: 'stats', href: '#stats', active: route === 'stats' },
    { id: 'board', label: t('Board'), icon: 'board', href: boardAddress, external: true, disabled: !boardAddress },
  ]);
  let settingsActive = $derived(route === 'settings');
</script>

<nav class="sidebar" aria-label={t('Main')}>
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
</nav>

<style>
  .sidebar {
    position: sticky; top: var(--header-h); height: calc(100vh - var(--header-h) - var(--footer-h));
    width: 240px; flex-shrink: 0; grid-row: 2; grid-column: 1;
    display: flex; flex-direction: column; padding: 1rem 0.75rem;
    background: var(--glass); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur);
    border-right: 1px solid var(--glass-border); box-shadow: var(--glass-bar-shadow);
    z-index: 30;
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

  @media (max-width: 800px) {
    .sidebar {
      position: fixed; top: auto; bottom: 0; left: 0; right: 0; width: auto; height: calc(var(--nav-h, 4.2rem) + env(safe-area-inset-bottom)); box-sizing: border-box; grid-row: auto; grid-column: auto;
      flex-direction: row; align-items: center; padding: 0.35rem 0.5rem calc(0.35rem + env(safe-area-inset-bottom));
      border-right: none; border-top: 1px solid var(--glass-border);
    }
    .items { flex-direction: row; flex: 1; justify-content: space-around; gap: 0; }
    .item { flex-direction: column; gap: 0.15rem; padding: 0.4rem 0.6rem; font-size: 0.7rem; border-left: none; }
    .item.active { border-left-color: transparent; }
    .settings { margin-top: 0; }
  }
</style>
