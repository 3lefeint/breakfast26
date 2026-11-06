<script>
  import { t } from '../../lib/i18n.js';
  // Settings → Stream Deck: the keys of a Stream Deck at the board. The grid shows the device (a 15-key layout
  // while none is plugged in); click a key to set its action, label and color. A key either follows the board
  // status (green on Throw, yellow around the take-out, red when stopped) or has a fixed color. Every change is
  // saved at once into `[streamdeck]` of config.toml and applies without a restart.
  import { onMount, onDestroy } from 'svelte';
  import Toggle from '../../lib/components/Toggle.svelte';
  import { apiJson } from '../../lib/api.js';
  import { confirmDialog } from '../../lib/confirm.js';

  const URL = '/api/streamdeck';
  const ACTION_LABEL = { reset_board: t('Reset Board'), start_board: t('Start Board'), undo: t('Undo'),
                         next_player: t('Next Player'), next_game: t('Next Game') };
  const SYMBOL_LABEL = { reset: t('Reset'), start: t('Start'), undo: t('Undo'), next_player: t('Next Player'), next_game: t('Next Game') };
  const SHOW_LABEL = { player: t('Player on turn'), remaining: t('Remaining score'), lives: t('Lives'),
                       darts: t('Darts in the turn'), round: t('Round') };
  const labelOf = (id) => ACTION_LABEL[id] || data?.actions.find((a) => a.id === id)?.label || '';
  const DEFAULT_HOLD = 0.8;
  const BOARD_STATUS_LABEL = { green: t('ready to throw'), yellow: t('take-out or starting'), red: t('stopped'), off: t('unknown') };

  let data = $state(null);
  let error = $state('');
  let selected = $state(null);
  let draft = $state({ action: '', label: '', color: '#000000', hold: 0, image: '', show: '' });
  let timer = null;

  async function load() {
    try {
      const body = await fetch(URL).then((r) => r.json());
      if (body.error) { error = body.error; data = null; } else { error = ''; data = body; }
    } catch (e) {
      error = t('Could not load the Stream Deck.');
    }
  }
  onMount(() => { load(); timer = setInterval(load, 2000); });
  onDestroy(() => clearInterval(timer));

  async function send(body) {
    const res = await apiJson('PUT', URL, body);
    if (res.error) { error = res.error; return false; }
    error = '';
    data = res;
    return true;
  }

  let keyCount = $derived(data ? data.rows * data.cols : 0);
  let cells = $derived(data ? Array.from({ length: keyCount }, (_, i) => data.keys.find((k) => k.key === i) || { key: i, empty: true }) : []);

  function select(i) {
    selected = selected === i ? null : i;
    const k = data?.keys.find((x) => x.key === i);
    draft = k ? { action: k.action, label: k.label, color: k.color, hold: k.hold, image: k.image, show: k.show } : { action: '', label: '', color: '#000000', hold: 0, image: '', show: '' };
  }

  // The whole layout with the draft applied to the selected key (or that key removed when it has no action).
  function layoutWith(i, d) {
    const others = data.keys.filter((k) => k.key !== i).map(({ key, action, label, color, hold, image, show }) => ({ key, action, label, color, hold, image, show }));
    return d.action || d.show ? [...others, { key: i, action: d.action, label: d.label, color: d.color, hold: d.hold, image: d.image, show: d.show }] : others;
  }

  async function chooseAction() {
    // A label that is still the name of the previous action follows the new action.
    const previous = data.keys.find((k) => k.key === selected);
    if (!draft.label || (previous && draft.label === labelOf(previous.action))) draft.label = labelOf(draft.action);
    // A board reset has to be held by default, so it is not run by a press by accident.
    if (!previous && draft.action === 'reset_board') draft.hold = DEFAULT_HOLD;
    await save();
  }

  async function chooseShow() {
    if (draft.show && !draft.label) draft.label = SHOW_LABEL[draft.show];
    await save();
  }

  async function save() {
    if (selected === null) return;
    await send({ keys: layoutWith(selected, draft) });
  }

  async function clearKey() {
    draft = { action: '', label: '', color: '#000000', hold: 0, image: '', show: '' };
    await save();
  }

  const setHold = (on) => { draft.hold = on ? DEFAULT_HOLD : 0; save(); };
  const holdTime = (e) => { draft.hold = Math.min(5, Math.max(0.2, Number(e.currentTarget.value) || DEFAULT_HOLD)); save(); };
  // ---- images ----
  let uploading = $state(false);
  const isFile = (v) => v && !v.startsWith('symbol:');
  // The preview of a key with an image is drawn by Breakfast itself, so it is what the device shows.
  const previewUrl = (c) => `${URL}/key/${c.key}.png?v=${encodeURIComponent([c.shown, c.label, c.image, c.value, data.images.join()].join('|'))}`;

  async function upload(event) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    uploading = true;
    try {
      const res = await fetch(`${URL}/images?name=${encodeURIComponent(file.name)}`, { method: 'POST', body: file }).then((r) => r.json());
      if (res.error) { error = res.error; return; }
      error = '';
      await load();
      draft.image = res.file;
      await save();
    } catch (e) {
      error = t('The upload failed.');
    } finally {
      uploading = false;
    }
  }

  async function deleteImage() {
    const name = draft.image;
    if (!await confirmDialog(t('Delete {file}? Keys that show it lose the image.', { file: name }))) return;
    const res = await apiJson('DELETE', `${URL}/images/${encodeURIComponent(name)}`);
    if (res.error) { error = res.error; return; }
    error = '';
    data = res;
    draft.image = '';
  }

  // ---- custom actions ----
  const METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'];
  const emptyAction = () => ({ id: '', name: '', kind: 'route', method: 'POST', target: '', body: '' });
  let editing = $state(null);          // the custom action in the form, null while there is none

  const newAction = () => { editing = emptyAction(); };
  const editAction = (a) => { editing = { ...a }; };
  const kindChanged = () => { if (!editing.target) editing.method = editing.kind === 'route' ? 'POST' : 'GET'; };

  async function saveAction() {
    const others = data.custom_actions.filter((a) => a.id !== editing.id);
    const kept = editing.id ? data.custom_actions.map((a) => (a.id === editing.id ? editing : a)) : [...others, editing];
    if (await send({ actions: kept })) editing = null;
  }

  async function deleteAction(a) {
    const used = data.keys.filter((k) => k.action === a.id).length;
    if (used && !await confirmDialog(t('{name} is on {n} key(s). Delete it and clear those keys?', { name: a.name, n: used }))) return;
    if (selected !== null && draft.action === a.id) selected = null;
    await send({ actions: data.custom_actions.filter((x) => x.id !== a.id) });
    if (editing?.id === a.id) editing = null;
  }

  const toggleEnabled = (value) => send({ enabled: value });
  const setBrightness = (e) => send({ brightness: Number(e.currentTarget.value) });
  const fixedColor = (e) => { draft.color = e.currentTarget.value; save(); };
  const followStatus = (e) => { draft.color = e.currentTarget.checked ? 'status' : (data.keys.find((k) => k.key === selected)?.shown || '#1faa59'); save(); };
  const textColor = (hex) => {
    const n = parseInt(hex.slice(1), 16);
    return ((n >> 16) * 299 + ((n >> 8) & 255) * 587 + (n & 255) * 114) / 1000 > 140 ? '#000' : '#fff';
  };
</script>

{#if error && !data}
  <div class="empty">{error}</div>
{:else if !data}
  <div class="empty">{t('Loading…')}</div>
{:else}
  <p class="intro">{t('Keys of a Stream Deck at the board: press one to run a board control, and the keys show the board status. Click a key to set it up.')}</p>

  <Toggle label={t('Use a Stream Deck')} checked={data.enabled} onchange={toggleEnabled} />

  <div class="device" class:ok={data.connected}>
    {#if !data.enabled}
      {t('Switched off.')}
    {:else if data.connected}
      {t('Connected: {model}', { model: data.model })}
    {:else if !data.library}
      {t('The USB library is not installed.')}
    {:else if data.device_error === 'no_hid_backend'}
      {t('The USB library finds no HID backend. Install libhidapi (package libhidapi-libusb0).')}
    {:else if data.device_error}
      {data.device_error}
    {:else}
      {t('No Stream Deck found. Plug it into this computer.')}
    {/if}
  </div>

  <div class="status">
    <span class="dot" style="background: {data.colors[data.status_color]}"></span>
    {t('Board')}: {data.board_status || t('unknown')} · {BOARD_STATUS_LABEL[data.status_color]}
  </div>

  <label class="brightness">
    <span>{t('Brightness')}</span>
    <input type="range" min="0" max="100" value={data.brightness} onchange={setBrightness}>
    <span class="val">{data.brightness} %</span>
  </label>

  <div class="grid" style="grid-template-columns: repeat({data.cols}, minmax(0, 1fr));" class:dim={!data.connected}>
    {#each cells as c (c.key)}
      <button type="button" class="key" class:selected={selected === c.key} class:empty={c.empty}
              style={c.empty ? '' : `background: ${c.shown}; color: ${textColor(c.shown)};`}
              onclick={() => select(c.key)} aria-label={t('Key {n}', { n: c.key + 1 })}>
        {#if c.empty}<span class="num">{c.key + 1}</span>
        {:else if c.image || c.show}<img class="keyimg" src={previewUrl(c)} alt={c.label}>
        {:else}{c.label}{/if}
      </button>
    {/each}
  </div>

  {#if selected !== null}
    <div class="editor">
      <div class="editor-title">{t('Key {n}', { n: selected + 1 })}</div>
      <label class="field">
        <span>{t('Action')}</span>
        <select bind:value={draft.action} onchange={chooseAction}>
          <option value="">{t('None')}</option>
          {#each data.actions.filter((a) => !a.custom) as a (a.id)}<option value={a.id}>{ACTION_LABEL[a.id]}</option>{/each}
          {#if data.custom_actions.length}
            <optgroup label={t('Custom actions')}>
              {#each data.actions.filter((a) => a.custom) as a (a.id)}<option value={a.id}>{a.label}</option>{/each}
            </optgroup>
          {/if}
        </select>
      </label>
      <label class="field">
        <span>{t('Show')}</span>
        <select bind:value={draft.show} onchange={chooseShow}>
          <option value="">{t('Nothing')}</option>
          {#each data.show_values as v (v)}<option value={v}>{SHOW_LABEL[v]}</option>{/each}
        </select>
      </label>
      {#if draft.action || draft.show}
        <label class="field">
          <span>{t('Label')}</span>
          <input type="text" maxlength="40" bind:value={draft.label} onchange={save}>
        </label>
        <div class="field">
          <span>{t('Color')}</span>
          <label class="follow">
            <input type="checkbox" checked={draft.color === 'status'} onchange={followStatus}>
            {t('Follow the board status')}
          </label>
          {#if draft.color !== 'status'}
            <input type="color" value={draft.color} onchange={fixedColor} aria-label={t('Color')}>
          {/if}
        </div>
        <label class="field">
          <span>{t('Image')}</span>
          <select bind:value={draft.image} onchange={save}>
            <option value="">{t('None')}</option>
            <optgroup label={t('Symbols')}>
              {#each data.symbols as sym (sym)}<option value={'symbol:' + sym}>{SYMBOL_LABEL[sym]}</option>{/each}
            </optgroup>
            {#if data.images.length}
              <optgroup label={t('Your images')}>
                {#each data.images as f (f)}<option value={f}>{f}</option>{/each}
              </optgroup>
            {/if}
          </select>
        </label>
        <div class="field">
          <span></span>
          <label class="act upload" class:busy={uploading}>
            {uploading ? t('Uploading…') : t('Upload an image')}
            <input type="file" accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp" onchange={upload} disabled={uploading}>
          </label>
          {#if isFile(draft.image)}<button type="button" class="act danger" onclick={deleteImage}>{t('Delete file')}</button>{/if}
        </div>
        {#if draft.action}<Toggle label={t('Hold to run')} checked={draft.hold > 0} onchange={setHold} />{/if}
        {#if draft.action && draft.hold > 0}
          <label class="field">
            <span>{t('Hold for (seconds)')}</span>
            <input type="number" min="0.2" max="5" step="0.1" value={draft.hold} onchange={holdTime}>
          </label>
        {/if}
        <button type="button" class="act danger" onclick={clearKey}>{t('Clear key')}</button>
      {/if}
    </div>
  {/if}

  <div class="custom">
    <div class="editor-title">{t('Custom actions')}</div>
    <p class="hint">{t('A custom action calls a route of Breakfast or a web address. Create it here, then pick it for a key.')}</p>
    {#if data.custom_actions.length}
      <ul class="custom-list">
        {#each data.custom_actions as a (a.id)}
          <li>
            <span class="cname">{a.name}</span>
            <span class="cmeta">{a.method} {a.kind === 'route' ? a.target : t('web address')}</span>
            <button type="button" class="act" onclick={() => editAction(a)}>{t('Edit')}</button>
            <button type="button" class="act danger" onclick={() => deleteAction(a)}>{t('Delete')}</button>
          </li>
        {/each}
      </ul>
    {/if}
    {#if editing}
      <div class="form">
        <label class="field"><span>{t('Name')}</span><input type="text" maxlength="40" bind:value={editing.name}></label>
        <label class="field"><span>{t('Kind')}</span>
          <select bind:value={editing.kind} onchange={kindChanged}>
            <option value="route">{t('Route of Breakfast')}</option>
            <option value="url">{t('Web address')}</option>
          </select>
        </label>
        <label class="field"><span>{t('Method')}</span>
          <select bind:value={editing.method}>{#each METHODS as m (m)}<option value={m}>{m}</option>{/each}</select>
        </label>
        <label class="field"><span>{editing.kind === 'route' ? t('Route') : t('Address')}</span>
          <input type="text" bind:value={editing.target} placeholder={editing.kind === 'route' ? '/api/control/undo' : 'https://…'}>
        </label>
        {#if editing.kind === 'url'}
          <label class="field"><span>{t('Body')}</span><textarea rows="3" bind:value={editing.body} placeholder={'{"key": "value"}'}></textarea></label>
        {/if}
        <div class="form-buttons">
          <button type="button" class="act" onclick={saveAction}>{t('Save')}</button>
          <button type="button" class="act" onclick={() => (editing = null)}>{t('Cancel')}</button>
        </div>
      </div>
    {:else}
      <button type="button" class="act" onclick={newAction}>{t('Add a custom action')}</button>
    {/if}
  </div>

  {#if error}<div class="message">{error}</div>{/if}
{/if}

<style>
  .empty { color: var(--muted); text-align: center; padding: 1.5rem 0; }
  .intro { color: var(--muted); font-size: 0.85rem; margin-bottom: 1rem; line-height: 1.45; }
  .device { font-size: 0.85rem; color: var(--muted); margin-bottom: 0.4rem; }
  .device.ok { color: var(--green); }
  .status { display: flex; align-items: center; gap: 0.5rem; font-size: 0.85rem; margin-bottom: 0.9rem; }
  .dot { width: 0.8rem; height: 0.8rem; border-radius: 50%; border: 1px solid var(--glass-border); }
  .brightness { display: flex; align-items: center; gap: 0.75rem; font-size: 0.9rem; color: var(--muted); margin-bottom: 1rem; }
  .brightness input { flex: 0 1 14rem; accent-color: var(--accent); }
  .val { font-size: 0.8rem; min-width: 3rem; }
  .grid { display: grid; gap: 0.5rem; max-width: 34rem; margin-bottom: 1rem; }
  .grid.dim { opacity: 0.85; }
  .key {
    aspect-ratio: 1; border-radius: 10px; border: 2px solid var(--glass-border); background: rgba(0, 0, 0, 0.25);
    font-family: inherit; font-size: 0.8rem; font-weight: 600; line-height: 1.15; padding: 0.2rem; cursor: pointer;
    overflow: hidden; word-break: break-word;
  }
  .key.empty { color: var(--muted); font-weight: 400; }
  .key:hover { border-color: var(--accent); }
  .key.selected { border-color: var(--accent); box-shadow: 0 0 14px -2px var(--accent); }
  .editor { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 8px; padding: 0.75rem 0.9rem; max-width: 34rem; }
  .editor-title { font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 0.6rem; }
  .field { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.6rem; font-size: 0.9rem; color: var(--muted); flex-wrap: wrap; }
  .field > span { min-width: 5rem; }
  .field select, .field input[type="text"] {
    flex: 1; min-width: 8rem; background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 6px;
    color: var(--text); padding: 0.35rem 0.55rem; font-family: inherit; font-size: 0.85rem;
  }
  .field input[type="number"] { width: 5rem; background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 6px; color: var(--text); padding: 0.35rem 0.55rem; font-family: inherit; font-size: 0.85rem; }
  .follow { display: flex; align-items: center; gap: 0.4rem; color: var(--text); font-size: 0.85rem; }
  input[type="color"] { width: 2.6rem; height: 1.8rem; padding: 0; border: 1px solid var(--glass-border); border-radius: 6px; background: none; }
  .act { background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 6px; color: var(--muted); padding: 0.25rem 0.8rem; font-family: inherit; font-size: 0.8rem; cursor: pointer; }
  .act:hover { border-color: var(--accent); color: var(--text); }
  .act.danger:hover { border-color: var(--red); color: var(--red); }
  .custom { margin-top: 1.25rem; max-width: 34rem; }
  .hint { color: var(--muted); font-size: 0.8rem; margin: 0 0 0.6rem; }
  .custom-list { list-style: none; padding: 0; margin: 0 0 0.75rem; }
  .custom-list li { display: flex; align-items: center; gap: 0.5rem; padding: 0.3rem 0; border-top: 1px solid var(--glass-border); flex-wrap: wrap; }
  .custom-list li:first-child { border-top: none; }
  .cname { font-size: 0.9rem; flex: 1; min-width: 6rem; }
  .cmeta { font-size: 0.75rem; color: var(--muted); word-break: break-all; }
  .form { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 8px; padding: 0.75rem 0.9rem; }
  .form textarea { flex: 1; min-width: 8rem; background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 6px; color: var(--text); padding: 0.35rem 0.55rem; font-family: ui-monospace, monospace; font-size: 0.8rem; }
  .form-buttons { display: flex; gap: 0.5rem; }
  .key.picture, .key:has(.keyimg) { padding: 0; }
  .keyimg { width: 100%; height: 100%; display: block; border-radius: 8px; object-fit: cover; }
  .upload { display: inline-block; cursor: pointer; }
  .upload.busy { opacity: 0.6; cursor: default; }
  .upload input { display: none; }
  .message { font-size: 0.85rem; color: var(--yellow); margin-top: 0.75rem; }
</style>
