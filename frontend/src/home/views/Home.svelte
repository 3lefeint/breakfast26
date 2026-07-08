<script>
  // Card/hub landing page (decided 2026-07-06) — Games/TV/Board/Players/
  // Stats/Settings. Explicitly not a hamburger menu or bottom tab bar.
  // Games is the featured/primary card (accent gradient, spans 2
  // columns) since starting a game is the most common action; the rest
  // sit in a regular grid. Cards stagger in on mount (fly + fade).
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
    { href: '#elimination', icon: '🎯', label: 'Games', sub: 'Elimination', featured: true },
    { href: '/tv', icon: '📺', label: 'TV', sub: 'Live display & controls' },
    { href: boardAddress, icon: '🎮', label: 'Board', sub: boardAddress ? 'Board manager' : 'Not configured', external: true, disabled: !boardAddress },
    { href: '#players', icon: '👤', label: 'Players' },
    { href: '#stats', icon: '📊', label: 'Stats' },
    { href: '#settings', icon: '⚙️', label: 'Settings' },
  ]);
</script>

<div class="hub">
  {#each cards as card, i (card.label)}
    <a
      class="card"
      class:featured={card.featured}
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
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
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
  .card.featured {
    grid-column: span 2;
    flex-direction: row;
    justify-content: flex-start;
    gap: 1rem;
    padding: 1.5rem 1.75rem;
    background:
      linear-gradient(135deg, color-mix(in srgb, var(--accent) 22%, var(--surface)), var(--surface) 65%);
    border-color: color-mix(in srgb, var(--accent) 35%, var(--border));
  }
  .card.featured .icon-badge {
    width: 3.5rem; height: 3.5rem; font-size: 1.6rem;
    background: color-mix(in srgb, var(--accent) 30%, var(--surface));
  }
  .card.featured .label { font-size: 1.15rem; }
  .card.featured .sub { text-align: left; }
  .icon-badge {
    display: flex; align-items: center; justify-content: center;
    width: 3rem; height: 3rem; border-radius: 999px;
    background: color-mix(in srgb, var(--accent) 16%, var(--surface));
    transition: transform 0.2s;
  }
  .icon { font-size: 1.4rem; line-height: 1; }
  .label { font-weight: 700; }
  .sub { font-size: 0.75rem; color: var(--muted); }
</style>
