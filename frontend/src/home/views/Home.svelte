<script>
  // The Play page: the games and the training drills as glass cards, in two sections. The
  // navigation to Players, Stats, Board and Settings and the link to the TV live in the shell.
  import { fly } from 'svelte/transition';
  import Icon from '../../lib/components/Icon.svelte';

  const SECTIONS = [
    { title: 'Multiplayer', columns: 3, cards: [
      { href: '#elimination', icon: 'elimination', label: 'Elimination', sub: 'Beat the last score' },
      { href: '#target-battle', icon: 'target-battle', label: 'Target Battle', sub: 'All throw at one number' },
      { href: '#killer', icon: 'killer', label: 'Killer', sub: 'Last one standing' },
    ] },
    { title: 'Singleplayer', columns: 2, cards: [
      { href: '#field-training', icon: 'field-training', label: 'Field Training', sub: 'Darts at one field' },
      { href: '#black-belt', icon: 'black-belt', label: 'Black Belt', sub: 'The doubles ladder' },
    ] },
  ];
</script>

{#each SECTIONS as section, s (section.title)}
  <h2>{section.title}</h2>
  <div class="grid" style="--columns: {section.columns}">
    {#each section.cards as card, i (card.label)}
      <a class="card" href={card.href} in:fly={{ y: 14, duration: 320, delay: (s * 3 + i) * 55 }}>
        <span class="icon-tile"><Icon name={card.icon} size={52} stroke={1.5} /></span>
        <span class="label">{card.label}</span>
        <span class="sub">{card.sub}</span>
        <span class="arrow"><Icon name="arrow" size={22} /></span>
      </a>
    {/each}
  </div>
{/each}

<style>
  h2 { font-size: 2.1rem; font-weight: 800; letter-spacing: -0.01em; margin: 0 0 1rem; }
  h2:not(:first-of-type) { margin-top: 2rem; }

  .grid { display: grid; grid-template-columns: repeat(var(--columns), 1fr); gap: 1.25rem; }
  .grid[style*="--columns: 2"] .card { min-height: 12.5rem; }
  .card {
    position: relative; display: flex; flex-direction: column; min-height: 14rem;
    padding: 1.25rem 1.4rem; border-radius: 16px; text-decoration: none; color: var(--text);
    background: var(--glass); border: 1px solid var(--glass-border);
    backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur);
    box-shadow: var(--glass-shadow);
    transition: border-color 0.2s, background 0.2s, transform 0.2s, box-shadow 0.2s;
  }
  .card:hover, .card:focus-visible {
    border-color: var(--accent); background: var(--glass-strong); transform: translateY(-3px); outline: none;
    box-shadow: var(--glass-shadow), 0 0 0 1px var(--accent), 0 18px 40px -14px color-mix(in srgb, var(--accent) 55%, transparent);
  }
  .icon-tile {
    display: flex; align-items: center; justify-content: center; width: 6.4rem; height: 6.4rem; margin-bottom: 1.1rem;
    border-radius: 12px; color: var(--accent);
    background: color-mix(in srgb, var(--accent) 16%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent) 25%, transparent);
  }
  .label { font-size: 1.9rem; font-weight: 700; letter-spacing: -0.01em; }
  .sub { margin-top: 0.3rem; font-size: 1.2rem; color: color-mix(in srgb, var(--text) 72%, transparent); }
  .arrow { position: absolute; right: 1.3rem; bottom: 1.15rem; color: var(--text); transition: transform 0.2s; }
  .card:hover .arrow { transform: translateX(4px); color: var(--accent); }

  @media (max-width: 900px) {
    .grid { grid-template-columns: repeat(2, 1fr); }
  }
  @media (max-width: 560px) {
    .grid { grid-template-columns: 1fr; }
    .card, .grid[style*="--columns: 2"] .card { min-height: 9rem; }
    .icon-tile { width: 4.5rem; height: 4.5rem; }
  }
</style>
