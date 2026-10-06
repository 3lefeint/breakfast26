<script>
  import { t } from '../i18n.js';
  // What an online match needs to say on the TV: who is playing where, that the match waits for
  // a site, the host's decision once it is gone for good, and anything that went wrong.
  import { onDestroy } from 'svelte';
  import { cap } from '../util.js';
  import { api } from '../api.js';

  let { online, currentPlayer = null } = $props();

  let now = $state(Date.now());
  const timer = setInterval(() => (now = Date.now()), 1000);
  onDestroy(() => clearInterval(timer));

  let seconds = $derived(online?.paused ? Math.max(0, Math.round((online.paused.rejoin_until - now) / 1000)) : 0);
  let owner = $derived(currentPlayer && online?.match ? online.match.owners[currentPlayer] : null);
  let remote = $derived(!!owner && owner !== online.site);

  const decide = (choice) => api('POST', '/api/online/decision', { choice });
</script>

{#if online}
  {#if online.decision}
    <div class="banner decide">
      <div>
        {t('{sites} did not come back.', { sites: online.decision.map((d) => d.site).join(', ') })}
        {#if online.host}
          {online.decision.length > 1 ? t('Play on without them (their players are out) or end the match?') : t('Play on without it (their players are out) or end the match?')}
        {:else}
          {t('The host decides how to go on.')}
        {/if}
      </div>
      {#if online.host}
        <div class="actions">
          <button class="btn-b" onclick={() => decide('continue')}>{t('Play on')}</button>
          <button class="btn-b danger" onclick={() => decide('abort')}>{t('End the match')}</button>
        </div>
      {/if}
    </div>
  {:else if online.phase === 'paused'}
    <div class="banner warn">{t('Waiting for {site} to reconnect…', { site: online.paused?.site })} {seconds ? `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}` : ''}</div>
  {:else if !online.connected}
    <div class="banner warn">{t('The connection to the relay is lost, reconnecting…')}</div>
  {:else if online.message}
    <div class="banner err">{online.message}</div>
  {/if}
  {#if remote && online.phase === 'playing'}
    <div class="remote">{t('{name} plays at {site}', { name: cap(currentPlayer), site: owner })}</div>
  {/if}
{/if}

<style>
  .banner { border-radius: 10px; padding: 0.6vw 1vw; margin-bottom: 1vw; font-size: clamp(0.8rem, 1.4vw, 1.4rem); border: 1px solid var(--border); background: var(--surface); }
  .banner.warn { border-color: var(--accent); color: var(--accent); }
  .banner.err, .banner.decide { border-color: var(--red); color: var(--text); }
  .actions { display: flex; gap: 0.6vw; margin-top: 0.5vw; }
  .btn-b { background: var(--bg); border: 1px solid var(--border); color: var(--text); border-radius: 8px; padding: 0.3vw 1vw; font: inherit; cursor: pointer; }
  .btn-b:hover { border-color: var(--accent); }
  .btn-b.danger:hover { border-color: var(--red); color: var(--red); }
  .remote { color: var(--muted); font-size: clamp(0.8rem, 1.3vw, 1.3rem); margin-bottom: 0.6vw; }
</style>
