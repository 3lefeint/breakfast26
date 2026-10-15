<script>
  import { t } from '../i18n.js';
  // Creates a new player and hands the name to the setup page, which puts it into its game.
  import { apiJson } from '../api.js';

  let { onadded } = $props();
  let name = $state('');

  async function add() {
    const n = name.trim();
    if (!n) return;
    const res = await apiJson('POST', '/api/players', { name: n });
    if (res.error) { alert(t(res.error)); return; }
    name = '';
    onadded(n);
  }
</script>

<div class="add-row">
  <input class="text-input" placeholder={t('New player')} bind:value={name} onkeydown={(e) => e.key === 'Enter' && add()}>
  <button type="button" class="btn-small" onclick={add}>{t('Add player')}</button>
</div>

<style>
  .add-row { display: flex; gap: 0.5rem; max-width: 34rem; margin-top: 0.7rem; }
  .text-input { flex: 1; min-width: 0; background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 12px; color: var(--text); padding: 0.3rem 0.6rem; font-family: inherit; }
  .btn-small { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); border-radius: 12px; padding: 0.3rem 0.9rem; font-family: inherit; cursor: pointer; }
  .btn-small:hover { border-color: var(--accent); }
</style>
