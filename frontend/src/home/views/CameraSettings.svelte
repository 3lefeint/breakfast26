<script>
  import { t } from '../../lib/i18n.js';
  // Which camera is camera 1 to 3 of the board, chosen by USB port from the cameras that are plugged in (the folder the udev rule of the
  // Linux installer fills). `ports` is the choice, three different ports or null; it is saved with the Settings form and applies after a restart.
  import { onMount } from 'svelte';
  import { apiJson } from '../../lib/api.js';

  let { ports = $bindable(null) } = $props();

  let found = $state([]);
  let choice = $state([ports?.[0] ?? '', ports?.[1] ?? '', ports?.[2] ?? '']);
  let loaded = $state(false);
  let tick = $state(0);
  let missing = $state({});            // port -> the picture could not be taken

  async function load() {
    const res = await apiJson('GET', '/api/detection/cameras');
    if (!res.found) return;
    found = res.found;
    if (!loaded) {
      loaded = true;
      if (!ports) choice = res.slots.map((s) => s.port ?? '');
    }
    tick += 1;
  }
  onMount(() => {
    load();
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  });

  const options = (i) => [...new Set([...found, ...(choice[i] ? [choice[i]] : [])])].sort();
  const complete = $derived(choice.every(Boolean) && new Set(choice).size === 3);
  const labelOf = (port) => {
    const i = choice.indexOf(port);
    return i < 0 ? port : `${t('Camera {n}', { n: i + 1 })} · ${port}`;
  };

  function pick(i, port) {
    choice[i] = port;
    if (complete) ports = [...choice];
  }
</script>

<div class="cameras">
  <div class="title">{t('Board cameras')} <span class="badge">{t('needs a restart')}</span></div>
  <p class="note">{t('Choose which camera is which, in the order of the board. The cameras are told apart by their USB port, so they keep their place when they are plugged in again.')}</p>
  {#each [0, 1, 2] as i (i)}
    <div class="row">
      <label for={`cam${i}`}>{t('Camera {n}', { n: i + 1 })}</label>
      <select id={`cam${i}`} value={choice[i]} onchange={(e) => pick(i, e.currentTarget.value)}>
        <option value="">{t('Not chosen')}</option>
        {#each options(i) as port (port)}
          <option value={port}>{t('USB port {port}', { port })}{found.includes(port) ? '' : ` (${t('not found')})`}</option>
        {/each}
      </select>
      {#if choice[i]}
        <span class="state" class:bad={!found.includes(choice[i])}>{found.includes(choice[i]) ? t('found') : t('not found')}</span>
      {/if}
    </div>
  {/each}
  {#if !complete}<p class="note warn">{t('Choose three different cameras')}</p>{/if}
  {#if found.length}
    <div class="pictures">
      {#each found as port (port)}
        <figure>
          {#if missing[port]}
            <div class="none">{t('No picture')}</div>
          {:else}
            <img src={`/api/detection/cameras/frame/${port}?t=${tick}`} alt={labelOf(port)} onerror={() => (missing[port] = true)} onload={() => (missing[port] = false)}>
          {/if}
          <figcaption>{labelOf(port)}</figcaption>
        </figure>
      {/each}
    </div>
  {:else}
    <p class="note">{t('No camera found. Plug them in; the Linux installer sets the host up for this.')}</p>
  {/if}
</div>

<style>
  .cameras { margin: 0.8rem 0; }
  .title { font-weight: 600; margin-bottom: 0.3rem; }
  .badge { font-size: 0.7rem; font-weight: 400; padding: 0.1rem 0.45rem; border-radius: 999px; background: rgba(251,191,36,0.12); color: var(--yellow); margin-left: 0.4rem; }
  .note { font-size: 0.8rem; color: var(--muted); margin: 0.2rem 0 0.6rem; }
  .note.warn { color: var(--yellow); }
  .row { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.4rem; }
  label { min-width: 6rem; font-size: 0.9rem; color: var(--muted); }
  select { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 8px; padding: 0.3rem 0.5rem; font: inherit; }
  .state { font-size: 0.8rem; color: var(--green); }
  .state.bad { color: var(--red); }
  .pictures { display: grid; grid-template-columns: repeat(auto-fill, minmax(11rem, 1fr)); gap: 0.6rem; margin-top: 0.6rem; }
  figure { margin: 0; }
  img, .none { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; border-radius: 8px; background: var(--glass); display: block; }
  .none { display: flex; align-items: center; justify-content: center; color: var(--muted); font-size: 0.8rem; }
  figcaption { font-size: 0.78rem; color: var(--muted); margin-top: 0.2rem; }
</style>
