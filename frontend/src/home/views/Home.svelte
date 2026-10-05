<script>
  // Card/hub landing page (decided 2026-07-06). Explicitly not a hamburger
  // menu or bottom tab bar. Rows: the games and the TV (four cards), the
  // training, then Players and Stats, then Board and Settings (two cards each, half the
  // width). Cards stagger in on mount (fly + fade).
  import { onMount } from 'svelte';
  import { fly } from 'svelte/transition';

  let boardAddress = $state(null);

  onMount(async () => {
    try {
      const r = await fetch('/api/board-address').then((res) => res.json());
      if (r.address) boardAddress = r.address;
    } catch (_) {
      // no board manager configured — Board card just won't link out
    }
  });

  let cards = $derived([
    { href: '#elimination', icon: '🎯', label: 'Elimination', sub: 'Beat the last score' },
    { href: '#target-battle', icon: '🎡', label: 'Target Battle', sub: 'All throw at one number' },
    { href: '#killer', icon: '🗡️', label: 'Killer', sub: 'Last one standing' },
    { href: '/tv', icon: '📺', label: 'TV', sub: 'Live display & controls' },
    { href: '#field-training', icon: '🏋️', label: 'Field Training', sub: 'Darts at one field' },
    { href: '#players', icon: '👤', label: 'Players', wide: true, newRow: true },
    { href: '#stats', icon: '📊', label: 'Stats', wide: true },
    { href: boardAddress, icon: '🎮', label: 'Board', sub: boardAddress ? 'Board manager' : 'Not configured', external: true, disabled: !boardAddress, wide: true },
    { href: '#settings', icon: '⚙️', label: 'Settings', wide: true },
  ]);
</script>

<div class="hub">
  {#each cards as card, i (card.label)}
    <a
      class="card"
      class:wide={card.wide}
      class:new-row={card.newRow}
      class:disabled={card.disabled}
      href={card.disabled ? undefined : card.href}
      target={card.external ? '_blank' : undefined}
      rel={card.external ? 'noopener' : undefined}
      in:fly={{ y: 14, duration: 320, delay: i * 55 }}
    >
      <div class="icon-badge"><span class="icon">{card.icon}</span></div>
      <div class="label">{card.label}</div>
      {#if card.sub}<div class="sub">{card.sub}</div>{/if}
    </a>
  {/each}
</div>

<style>
  .hub {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 1rem;
  }
  .card {
    position: relative;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 0.5rem; text-align: center;
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 16px; padding: 1.75rem 1rem;
    color: var(--text); text-decoration: none;
    transition: border-color 0.2s, transform 0.2s, box-shadow 0.2s;
  }
  .card:hover {
    border-color: color-mix(in srgb, var(--accent) 60%, var(--border));
    transform: translateY(-3px);
    box-shadow: 0 10px 28px -12px color-mix(in srgb, var(--accent) 45%, transparent);
  }
  .card:hover .icon-badge { transform: scale(1.08); }
  .card.disabled { opacity: 0.4; pointer-events: none; }
  .card.wide { grid-column: span 2; }
  .icon-badge {
    display: flex; align-items: center; justify-content: center;
    width: 3rem; height: 3rem; border-radius: 999px;
    background: color-mix(in srgb, var(--accent) 16%, var(--surface));
    transition: transform 0.2s;
  }
  .icon { font-size: 1.4rem; line-height: 1; }
  .label { font-weight: 700; }
  .sub { font-size: 0.75rem; color: var(--muted); }

  /* The training cards have a row of their own; what follows starts a new one. */
  @media (min-width: 641px) {
    .card.new-row { grid-column: 1 / span 2; }
  }

  /* Narrow screens: two cards per row, in the same order. */
  @media (max-width: 640px) {
    .hub { grid-template-columns: repeat(2, 1fr); }
    .card.wide { grid-column: span 1; }
  }
</style>
