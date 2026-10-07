<script>
  // Outline icons in one stroke style, drawn on a 24 x 24 grid. `name` picks the icon.
  let { name, size = 24, stroke = 1.75 } = $props();

  const ICONS = {
    // Games
    elimination: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="2.2"/><path d="M12 1.5v5M12 17.5v5M1.5 12h5M17.5 12h5"/>',
    'target-battle': '<circle cx="12" cy="12" r="9.5"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2"/><path d="M12 2.5v9M12 12.5v9M2.5 12h9M12.5 12h9M5.3 5.3l6.4 6.4M12.3 12.3l6.4 6.4M18.7 5.3l-6.4 6.4M11.7 12.3l-6.4 6.4"/>',
    killer: '<path d="M21 3 9 15M3 3l12 12"/><path d="M21 3h-4.5M21 3v4.5M3 3h4.5M3 3v4.5"/><path d="M5 15h4v4M19 15h-4v4"/>',
    'field-training': '<circle cx="12" cy="12" r="9.5"/><circle cx="12" cy="12" r="5.5"/><circle cx="12" cy="12" r="1.6"/>',
    checkout: '<circle cx="12" cy="12" r="9.5"/><path d="M7.5 12.5l3 3.2 6-7"/>',
    'black-belt': '<path d="M2 8.5c3 0 5 .3 7 .8v6.4c-2-.5-4-.8-7-.8z"/><path d="M22 8.5c-3 0-5 .3-7 .8v6.4c2-.5 4-.8 7-.8z"/><rect x="9" y="7" width="6" height="10" rx="1.8"/><path d="M10.3 17 8.6 21.5l2.4-.5 1-2M13.7 17l1.7 4.5-2.4-.5-1-2"/>',
    // Navigation
    play: '<circle cx="12" cy="12" r="9.5"/><path d="M12 12l4.2-4.2"/><path d="M7.5 7.5l.9.9M12 5.2v1.3M16.5 7.5l-.9.9M5.2 12h1.3"/>',
    players: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    stats: '<path d="M21.2 15.9A10 10 0 1 1 8 2.8"/><path d="M22 12A10 10 0 0 0 12 2v10z"/>',
    board: '<circle cx="12" cy="12" r="9.5"/><circle cx="12" cy="12" r="4.5"/>',
    settings: '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
    tv: '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
    trophy: '<path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6M18 9h1.5a2.5 2.5 0 0 0 0-5H18M4 22h16M10 14.66V17c0 .55-.47.98-1.04 1.21C7.85 18.75 7 20.24 7 22M14 14.66V17c0 .55.47.98 1.04 1.21C16.15 18.75 17 20.24 17 22M18 2H6v7a6 6 0 0 0 12 0V2z"/>',
    'volume-off': '<path d="M11 5 6 9H2v6h4l5 4V5zM22 9l-6 6M16 9l6 6"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    chevron: '<path d="M9 18l6-6-6-6"/>',
    back: '<path d="M15 18l-6-6 6-6"/>',
    arrow: '<path d="M5 12h14M12 5l7 7-7 7"/>',
    info: '<circle cx="12" cy="12" r="9.5"/><path d="M12 11v5.5M12 7.5v.01"/>',
  };
</script>

<svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width={stroke}
     stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  {@html ICONS[name] || ''}
</svg>
