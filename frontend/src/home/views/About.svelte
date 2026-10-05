<script>
  // The running version and release time, a joke of the day and the changelog.
  import { onMount } from 'svelte';
  import { health } from '../../lib/stores/health.js';
  import PageHeader from '../../lib/components/PageHeader.svelte';
  import logo from '../../lib/assets/logo.png';

  let versions = $state([]);
  let joke = $state(null);   // null: not loaded or switched off

  onMount(async () => {
    try {
      versions = (await fetch('/api/changelog').then((r) => r.json())).versions ?? [];
    } catch (_) { /* the page still shows the version */ }
    try {
      const res = await fetch('/api/joke').then((r) => r.json());
      joke = res.enabled ? res.joke : null;
    } catch (_) { /* no joke today */ }
  });

  // 2026-10-01T22:11:52Z -> "1 Oct 2026, 22:11 UTC"
  function released(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' }) + ' UTC';
  }
</script>

<PageHeader title="About" />

<div class="tiles">
  <div class="tile"><div class="label">App</div><div class="value brand"><img src={logo} alt="" width="40" height="40">Breakfast</div></div>
  <div class="tile"><div class="label">Version</div><div class="value">{$health.version ? `v${$health.version}` : '—'}</div></div>
  <div class="tile"><div class="label">Released</div><div class="value small">{released($health.releaseDate)}</div></div>
</div>

{#if joke}
  <div class="card">
    <div class="card-title">Joke of the day</div>
    <p class="joke">{joke}</p>
  </div>
{/if}

<div class="subtitle">Changelog</div>
{#each versions as v}
  <div class="card version">
    <div class="version-head">
      <span class="version-name">{v.version === 'Unreleased' ? 'Unreleased' : `v${v.version}`}</span>
      {#if v.date}<span class="version-date">{v.date}</span>{/if}
    </div>
    {#each v.sections as s}
      {#if s.name}<div class="section-name">{s.name}</div>{/if}
      <ul>
        {#each s.entries as e}<li>{e}</li>{/each}
      </ul>
    {/each}
  </div>
{:else}
  <div class="empty">No changelog available.</div>
{/each}

<style>
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 0.75rem; }
  .tile { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 14px; box-shadow: var(--glass-shadow); padding: 1rem 1.1rem; text-align: center; }
  .tile .label { font-size: 0.72rem; color: var(--muted); margin-bottom: 0.4rem; text-transform: uppercase; letter-spacing: 0.08em; font-weight: 700; }
  .tile .value { font-size: 1.5rem; font-weight: 700; }
  .tile .value.brand { display: flex; align-items: center; justify-content: center; gap: 0.5rem; }
  .tile .value.brand img { margin: -6px 0; }
  .tile .value.small { font-size: 1rem; line-height: 2.1rem; }
  .card { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 16px; box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); padding: 1.1rem 1.3rem; margin-top: 1rem; }
  .card-title { font-size: 0.75rem; color: var(--muted); margin-bottom: 0.6rem; text-transform: uppercase; letter-spacing: 0.08em; font-weight: 700; }
  .joke { font-size: 1.05rem; line-height: 1.55; }
  .subtitle { font-size: 0.8rem; color: var(--muted); font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; margin: 2rem 0 0.75rem; }
  .subtitle + .card { margin-top: 0; }
  .version-head { display: flex; align-items: baseline; gap: 0.6rem; margin-bottom: 0.4rem; }
  .version-name { font-weight: 800; font-size: 1.1rem; color: var(--accent); }
  .version-date { font-size: 0.75rem; color: var(--muted); }
  .section-name { font-size: 0.7rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; margin: 0.6rem 0 0.2rem; }
  ul { list-style: none; padding: 0; }
  li { font-size: 0.9rem; line-height: 1.5; color: color-mix(in srgb, var(--text) 85%, transparent); padding: 0.15rem 0 0.15rem 1rem; position: relative; }
  li::before { content: '•'; position: absolute; left: 0.2rem; color: var(--muted); }
  .empty { color: var(--muted); font-size: 0.8rem; text-align: center; padding: 1rem 0; }
</style>
