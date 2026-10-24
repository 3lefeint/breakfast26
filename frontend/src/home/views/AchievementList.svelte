<script>
  import { t } from '../../lib/i18n.js';
  // Settings → Achievement list (shown with the Dev tab): every achievement with the condition that earns it, to
  // filter and look through. Secret ones are included, so the list opens like the Dev tab.
  import { onMount } from 'svelte';
  import Badge from '../../lib/components/Badge.svelte';

  const MODES = { general: t('General'), x01: 'X01', elimination: t('Elimination'), killer: t('Killer'),
                  target_battle: t('Target Battle'), field_training: t('Field Training'), black_belt: t('Black Belt'), easter_egg: t('Easter eggs') };
  const DIFFICULTIES = { easy: t('Easy'), medium: t('Medium'), hard: t('Hard'), very_hard: t('Very hard'),
                         extreme: t('Extreme'), endurance: t('Endurance'), hidden: t('Hidden') };
  const APPLIES = { any: t('any game'), x01: t('X01 only'), elimination: t('Elimination only'), target_battle: t('Target Battle only'),
                    killer: t('Killer only'), field_training: t('Field Training only'), black_belt: t('Black Belt only') };
  const KINDS = { event: t('Event'), counter: t('Counter') };
  const FLAGS = { secret: [t('Secret'), (a) => a.hidden], live: [t('Live'), (a) => a.live], practice: [t('Counts in practice'), (a) => a.practice] };

  let list = $state(null);
  let error = $state('');
  let search = $state('');
  let mode = $state('all');
  let difficulty = $state('all');
  let kind = $state('all');
  let flag = $state('all');
  let open = $state(null);

  onMount(async () => {
    try {
      const body = await fetch('/api/dev/achievements').then((r) => r.json());
      if (body.error) error = body.error; else list = body.achievements;
    } catch (e) {
      error = t('Could not load the achievements.');
    }
  });

  // The badge as it looks once earned in full, a secret one with its motif too.
  const badge = (a) => ({ ...a, hidden: false, tier: a.tiers ? a.tiers.length : 1 });
  const kindOf = (a) => (a.tiers ? 'counter' : 'event');
  let rows = $derived((list || []).filter((a) =>
    (mode === 'all' || a.mode === mode)
    && (difficulty === 'all' || a.difficulty === difficulty)
    && (kind === 'all' || kindOf(a) === kind)
    && (flag === 'all' || FLAGS[flag][1](a))
    && (!search.trim() || `${a.id} ${a.names.en} ${a.names.de} ${a.descriptions.en} ${a.descriptions.de}`.toLowerCase().includes(search.trim().toLowerCase()))));
</script>

{#if error}
  <div class="empty">{error.startsWith('locked') ? t('Unlock the Dev tab first.') : error}</div>
{:else if !list}
  <div class="empty">{t('Loading…')}</div>
{:else}
  <div class="toolbar">
    <input type="search" placeholder={t('Search')} bind:value={search} aria-label={t('Search achievements')}>
    <select bind:value={mode} aria-label={t('Game mode')}>
      <option value="all">{t('All modes')}</option>
      {#each Object.entries(MODES) as [key, label]}<option value={key}>{label}</option>{/each}
    </select>
    <select bind:value={difficulty} aria-label={t('Difficulty')}>
      <option value="all">{t('All difficulties')}</option>
      {#each Object.entries(DIFFICULTIES) as [key, label]}<option value={key}>{label}</option>{/each}
    </select>
    <select bind:value={kind} aria-label={t('Kind')}>
      <option value="all">{t('Event and counter')}</option>
      {#each Object.entries(KINDS) as [key, label]}<option value={key}>{label}</option>{/each}
    </select>
    <select bind:value={flag} aria-label={t('Property')}>
      <option value="all">{t('Any property')}</option>
      {#each Object.entries(FLAGS) as [key, [label]]}<option value={key}>{label}</option>{/each}
    </select>
  </div>
  <div class="count">{t('{shown} of {total} achievements', { shown: rows.length, total: list.length })}</div>

  <ul class="list">
    {#each rows as a (a.id)}
      <li>
        <button type="button" class="row" aria-expanded={open === a.id} onclick={() => (open = open === a.id ? null : a.id)}>
          <Badge item={badge(a)} size={56} />
          <span class="text">
          <span class="head">
            <span class="name">{a.names.en}</span>
            <span class="chip">{MODES[a.mode] || a.mode}</span>
            <span class="chip">{DIFFICULTIES[a.difficulty] || a.difficulty}</span>
            {#if a.tiers}<span class="chip">{t('tiers {list}', { list: a.tiers.join(' · ') })}</span>{/if}
            {#if a.hidden}<span class="chip secret">{t('Secret')}</span>{/if}
          </span>
          <span class="condition">{a.descriptions.en}</span>
          </span>
        </button>
        {#if open === a.id}
          <dl class="detail">
            <dt>{t('Id')}</dt><dd><code>{a.id}</code></dd>
            <dt>{t('German')}</dt><dd>{a.names.de} – {a.descriptions.de}</dd>
            <dt>{t('Decided in')}</dt><dd>{APPLIES[a.applies] || a.applies}</dd>
            <dt>{t('Kind')}</dt>
            <dd>
              {#if a.tiers}
                {t('Counter')}: {a.peak ? t('the best single match counts') : t('adds up over matches')}
              {:else}
                {t('Event, earned once')}
              {/if}
            </dd>
            <dt>{t('Announced')}</dt><dd>{a.live ? t('while the match runs (provisional until it ends)') : t('when the match ends')}</dd>
            {#if a.practice}<dt>{t('Field Training')}</dt><dd>{t('also earned by a run that is only practice')}</dd>{/if}
            {#if a.label}<dt>{t('Badge text')}</dt><dd>{a.label}</dd>{/if}
          </dl>
        {/if}
      </li>
    {/each}
  </ul>
  {#if !rows.length}<div class="empty">{t('No achievement matches.')}</div>{/if}
{/if}

<style>
  .empty { color: var(--muted); text-align: center; padding: 1.5rem 0; }
  code { background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 4px; padding: 0 0.3rem; }
  .toolbar { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.5rem; }
  input[type="search"], select {
    background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 6px; color: var(--text);
    padding: 0.4rem 0.6rem; font-family: inherit; font-size: 0.85rem;
  }
  input[type="search"] { flex: 1; min-width: 10rem; }
  .count { font-size: 0.8rem; color: var(--muted); margin-bottom: 0.6rem; }
  .list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.5rem; }
  .list li { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 8px; }
  .row {
    display: flex; align-items: center; gap: 0.8rem; width: 100%; text-align: left; background: none; border: none;
    color: inherit; font: inherit; cursor: pointer; padding: 0.65rem 0.8rem;
  }
  .text { display: flex; flex-direction: column; gap: 0.3rem; min-width: 0; }
  .head { display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; }
  .name { font-weight: 700; margin-right: 0.3rem; }
  .chip { font-size: 0.7rem; color: var(--muted); border: 1px solid var(--glass-border); border-radius: 999px; padding: 0 0.5rem; }
  .chip.secret { color: var(--yellow); }
  .condition { font-size: 0.85rem; color: var(--muted); }
  .detail { display: grid; grid-template-columns: max-content 1fr; gap: 0.25rem 0.9rem; margin: 0; padding: 0 0.8rem 0.7rem; font-size: 0.82rem; }
  .detail dt { color: var(--muted); }
  .detail dd { margin: 0; }
</style>
