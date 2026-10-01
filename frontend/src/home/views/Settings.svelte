<script>
  // Mirrors index.html's #view-settings: config form (logging/mqtt/stats/
  // web/direct/audio/caller), theme application, voice-pack regeneration
  // with progress polling, and the Restart button. Reworked into category
  // tabs (General/MQTT/Autodarts Source/Voice & Caller) instead of one
  // long stacked page — Save stays persistent below the tab content
  // (saves the whole config regardless of which tab is showing); Restart
  // lives outside the tabs entirely since it's a whole-app action, not a
  // setting category.
  import { onMount } from 'svelte';
  import { gameState } from '../../lib/stores/gameState.js';
  import { api } from '../../lib/api.js';
  import PageHeader from '../../lib/components/PageHeader.svelte';

  const MASK = '●●●●●';
  const emptyCfg = () => ({
    logging: { level: 'INFO', events: false, file: '' },
    mqtt: { enabled: true, host: '', port: '', username: '', password: '', base_topic: '' },
    stats: { db: '' },
    web: { port: '', theme: 'default', accent_color: '' },
    direct: { email: '', password: '', board_id: '', board_ws_url: '', board_manager_url: '' },
    audio: { dir: '', profile: '' },
    caller: {
      enabled: true, per_dart: true, turn_total: true, checkout_limit: 1,
      announce_change: false, call_player: true, ambient_volume: 0.6, call_misses: true,
    },
    record: { file: '' },
    // Read-only — not part of the editable form/save flow, set directly in
    // config.toml. Only gates whether the Dev tab below is shown at all.
    dev: { enabled: false },
  });

  const TABS = [
    { id: 'general', label: 'General' },
    { id: 'mqtt', label: 'MQTT' },
    { id: 'source', label: 'Autodarts Source' },
    { id: 'voice', label: 'Voice & Caller' },
    { id: 'voicepack', label: 'Voice Pack' },
  ];
  let activeTab = $state('general');
  let tabs = $derived(cfg.dev?.enabled ? [...TABS, { id: 'dev', label: 'Dev' }] : TABS);

  let cfg = $state(emptyCfg());
  let voicePackProfiles = $state([]);
  // Snapshot of what was actually loaded from config.toml, so save() can
  // tell "field is empty because it was never set" apart from "field was
  // cleared just now" — only the latter should send an explicit null to
  // actually remove the key (see save()'s addIfChanged()).
  let loadedCfg = emptyCfg();
  let banner = $state(null); // { kind: 'ok'|'warn'|'error', text }
  let voicepackForce = $state(false);

  // Voice Pack tab — add/edit/browse/delete individual voice-pack entries,
  // separate from the whole-pack "Regenerate" flow above and from the
  // shared config Save (this tab writes tools/voicepack_leni.toml + sound
  // files directly, not config.toml).
  let vpGroups = $state([]);
  let vpSelectedGroup = $state('');
  let vpEntries = $state([]);
  let vpEntriesLoading = $state(false);
  let vpFormKey = $state('');
  let vpFormVariants = $state(['']);
  let vpSaving = $state(false);

  onMount(async () => {
    await loadConfig();
    await applyTheme();
    await loadVoicePackProfiles();
    await loadVoicepackGroups();
  });

  async function loadVoicepackGroups() {
    try {
      const res = await fetch('/api/voicepack/groups').then((r) => r.json());
      vpGroups = res.groups || [];
      if (!vpSelectedGroup && vpGroups.length) vpSelectedGroup = vpGroups[0].name;
      if (vpSelectedGroup) await loadVoicepackEntries();
    } catch (e) {
      console.error('loadVoicepackGroups failed:', e);
    }
  }

  async function loadVoicepackEntries() {
    vpEntriesLoading = true;
    try {
      const res = await fetch('/api/voicepack/entries?group=' + encodeURIComponent(vpSelectedGroup))
        .then((r) => r.json());
      vpEntries = res.entries || [];
    } catch (e) {
      console.error('loadVoicepackEntries failed:', e);
    } finally {
      vpEntriesLoading = false;
    }
  }

  function onVpGroupChange() {
    resetVpForm();
    loadVoicepackEntries();
  }

  function resetVpForm() {
    vpFormKey = '';
    vpFormVariants = [''];
  }

  function editVpEntry(entry) {
    vpFormKey = entry.key;
    vpFormVariants = entry.variants.map((v) => v.text);
  }

  function addVpVariantRow() {
    vpFormVariants = [...vpFormVariants, ''];
  }

  function removeVpVariantRow(i) {
    const next = vpFormVariants.filter((_, idx) => idx !== i);
    vpFormVariants = next.length ? next : [''];
  }

  async function playAudioBlobResponse(res) {
    const ct = res.headers.get('content-type') || '';
    if (!res.ok || !ct.includes('audio')) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || `HTTP ${res.status}`);
    }
    const blob = await res.blob();
    new Audio(URL.createObjectURL(blob)).play();
  }

  async function previewVpVariant(text) {
    if (!text.trim()) return;
    try {
      const res = await fetch('/api/voicepack/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ group: vpSelectedGroup, text }),
      });
      await playAudioBlobResponse(res);
    } catch (e) {
      alert('Preview failed: ' + e.message);
    }
  }

  async function playVpFile(filename) {
    try {
      await playAudioBlobResponse(await fetch('/api/voicepack/file/' + encodeURIComponent(filename)));
    } catch (e) {
      alert('Playback failed: ' + e.message);
    }
  }

  async function saveVpEntry() {
    const key = vpFormKey.trim();
    const variants = vpFormVariants.map((v) => v.trim()).filter(Boolean);
    if (!key || !variants.length) {
      alert('Key and at least one variant are required.');
      return;
    }
    vpSaving = true;
    try {
      const res = await fetch('/api/voicepack/entries', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ group: vpSelectedGroup, key, variants }),
      }).then((r) => r.json());
      if (res.error) { alert('Save failed: ' + res.error); return; }
      resetVpForm();
      await loadVoicepackEntries();
    } catch (e) {
      alert('Save failed: ' + e);
    } finally {
      vpSaving = false;
    }
  }

  async function deleteVpVariant(key, index) {
    if (!confirm('Delete this variant?')) return;
    try {
      const res = await fetch('/api/voicepack/entries', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ group: vpSelectedGroup, key, variant_index: index }),
      }).then((r) => r.json());
      if (res.error) { alert('Delete failed: ' + res.error); return; }
      await loadVoicepackEntries();
    } catch (e) {
      alert('Delete failed: ' + e);
    }
  }

  async function loadVoicePackProfiles() {
    try {
      const res = await fetch('/api/voice-packs').then((r) => r.json());
      voicePackProfiles = res.profiles || [];
    } catch (e) {
      console.error('loadVoicePackProfiles failed:', e);
    }
  }

  async function loadConfig() {
    try {
      const loaded = await fetch('/api/config').then((r) => r.json());
      if (loaded.error) return;
      const fresh = emptyCfg();
      for (const section of Object.keys(fresh)) {
        if (loaded[section]) Object.assign(fresh[section], loaded[section]);
      }
      cfg = fresh;
      loadedCfg = JSON.parse(JSON.stringify(fresh));
    } catch (e) {
      console.error('loadConfig failed:', e);
    }
  }

  async function applyTheme() {
    try {
      const loaded = await fetch('/api/config').then((r) => r.json());
      if (loaded.web?.theme) document.documentElement.dataset.theme = loaded.web.theme;
      if (loaded.web?.accent_color) {
        document.documentElement.style.setProperty('--accent', loaded.web.accent_color);
      }
    } catch (_) {
      // no config yet — keep default theme
    }
  }

  async function save(e) {
    e.preventDefault();
    const updates = {};

    // Optional text/number fields — only sent when changed from what was
    // actually loaded, so an untouched field never gets flagged as a
    // "restart required" change. A field that changed to empty (the user
    // cleared it) is sent as `null`, which config.write() treats as
    // "remove this key" — that's what actually gets a cleared value out of
    // config.toml, instead of leaving an empty string sitting there forever.
    const addIfChanged = (section, key, rawVal, parse) => {
      if (rawVal === MASK) return; // untouched secret placeholder — leave alone
      const oldVal = loadedCfg[section]?.[key];
      if (rawVal === oldVal) return; // unchanged
      const isEmpty = rawVal === '' || rawVal == null;
      if (isEmpty && (oldVal === '' || oldVal == null)) return; // was already empty
      if (isEmpty) {
        (updates[section] ??= {})[key] = null;
        return;
      }
      const val = parse ? parse(rawVal) : rawVal;
      if (parse && Number.isNaN(val)) return; // invalid number input — ignore
      (updates[section] ??= {})[key] = val;
    };

    addIfChanged('logging', 'file', cfg.logging.file);
    addIfChanged('mqtt', 'host', cfg.mqtt.host);
    addIfChanged('mqtt', 'username', cfg.mqtt.username);
    addIfChanged('mqtt', 'password', cfg.mqtt.password);
    addIfChanged('mqtt', 'base_topic', cfg.mqtt.base_topic);
    addIfChanged('stats', 'db', cfg.stats.db);
    addIfChanged('direct', 'email', cfg.direct.email);
    addIfChanged('direct', 'password', cfg.direct.password);
    addIfChanged('direct', 'board_id', cfg.direct.board_id);
    addIfChanged('direct', 'board_ws_url', cfg.direct.board_ws_url);
    addIfChanged('direct', 'board_manager_url', cfg.direct.board_manager_url);
    addIfChanged('audio', 'dir', cfg.audio.dir);
    addIfChanged('audio', 'profile', cfg.audio.profile);
    addIfChanged('web', 'accent_color', cfg.web.accent_color);
    addIfChanged('record', 'file', cfg.record.file);
    addIfChanged('mqtt', 'port', cfg.mqtt.port, (v) => parseInt(v, 10));
    addIfChanged('caller', 'checkout_limit', cfg.caller.checkout_limit, (v) => parseInt(v, 10));
    addIfChanged('caller', 'ambient_volume', cfg.caller.ambient_volume, (v) => parseFloat(v));

    // Selects — always a concrete value, no "clear" concept; send as-is.
    const addTo = (section, key, val) => { (updates[section] ??= {})[key] = val; };
    addTo('logging', 'level', cfg.logging.level);
    addTo('web', 'theme', cfg.web.theme);

    // Checkboxes — always included.
    (updates.logging ??= {}).events = cfg.logging.events;
    (updates.mqtt ??= {}).enabled = cfg.mqtt.enabled;
    (updates.web ??= {}).joke_of_the_day = cfg.web.joke_of_the_day;
    for (const key of ['enabled', 'per_dart', 'turn_total', 'announce_change', 'call_player', 'call_misses']) {
      (updates.caller ??= {})[key] = cfg.caller[key];
    }

    try {
      const res = await fetch('/api/config', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      }).then((r) => r.json());
      showBanner(res);
      delete document.documentElement.dataset.theme;
      document.documentElement.style.removeProperty('--accent');
      await applyTheme();
    } catch (err) {
      alert('Save failed: ' + err);
    }
  }

  function showBanner(res) {
    if (!res.saved) {
      banner = { kind: 'error', text: 'Save failed.' };
    } else if (res.restart_required?.length) {
      banner = { kind: 'warn', text: `Saved. Restart required to apply: ${res.restart_required.join(', ')}` };
    } else {
      banner = { kind: 'ok', text: 'Saved. Changes applied immediately.' };
    }
    setTimeout(() => { banner = null; }, 8000);
  }

  async function regenerateVoicepack() {
    if (voicepackForce && !confirm('Regenerate the ENTIRE voice pack? This can take several minutes.')) return;
    const res = await api('POST', '/api/voicepack/generate', { force: voicepackForce })
      .then(() => ({}))
      .catch((err) => ({ error: String(err) }));
    if (res && res.error) alert('Could not start: ' + res.error);
  }

  async function startDemo(mode) {
    // Not using the shared api() helper here — it discards the response
    // body, but the backend's "already running" / "real match in progress"
    // guard messages (returned as {started:false, error} with a 200 status)
    // are exactly what's useful to show the user for this action.
    const res = await fetch(`/api/dev/demo/${mode}`, { method: 'POST' })
      .then((r) => r.json())
      .catch((err) => ({ started: false, error: String(err) }));
    if (!res?.started) alert('Could not start demo: ' + (res?.error || 'unknown error'));
  }

  async function restartApp() {
    if (!confirm('Restart Breakfast now? The app will be briefly unavailable while it restarts.')) return;
    await api('POST', '/api/control/restart');
  }

  // Self-update. checkForUpdate()/applyUpdate() talk to the
  // updater helper through this app's own /api/updates/* proxy — but
  // pollUntilBackUp() below polls /api/health directly (not proxied),
  // since this app's own container is what goes down during the update;
  // routing status through it would go dark for exactly the window that
  // matters.
  let updateChecking = $state(false);
  let updateApplying = $state(false);
  let updateInfo = $state(null);      // { current, latest, update_available } | { error }
  let updatePhaseText = $state('');
  let updateOutcome = $state(null);   // 'success' | 'rolled_back' | 'timeout' | null
  let updateOutcomeDetail = $state(null);

  async function checkForUpdate() {
    updateChecking = true;
    updateInfo = null;
    updateOutcome = null;
    try {
      updateInfo = await fetch('/api/updates/check').then((r) => r.json());
    } catch (e) {
      updateInfo = { error: String(e) };
    } finally {
      updateChecking = false;
    }
  }

  async function applyUpdate() {
    if (!updateInfo?.update_available) return;
    if (!confirm(`Install update to v${updateInfo.latest}? The app will be briefly unavailable while it rebuilds and restarts.`)) return;
    const res = await fetch('/api/updates/apply', { method: 'POST' })
      .then((r) => r.json())
      .catch((e) => ({ error: String(e) }));
    if (res.error || res.ok === false) {
      alert('Could not start the update: ' + (res.error || 'unknown error'));
      return;
    }
    updateApplying = true;
    updateOutcome = null;
    updateOutcomeDetail = null;
    updatePhaseText = 'Installing update — this can take a few minutes…';
    await pollUntilBackUp(updateInfo.latest);
  }

  async function pollUntilBackUp(expectedVersion) {
    const deadline = Date.now() + 8 * 60 * 1000;
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 3000));
      try {
        const health = await fetch('/api/health').then((r) => r.json());
        if (!health.version) continue;
        if (health.version === expectedVersion) {
          updateOutcome = 'success';
          updateApplying = false;
          updatePhaseText = '';
          setTimeout(() => location.reload(), 1500);
          return;
        }
        // Reachable but still on the old version: the updater is most likely
        // still building (the old container keeps serving until the new one
        // replaces it). Only the updater's own status says whether it
        // actually gave up and rolled back.
        const status = await fetch('/api/updates/status').then((r) => r.json());
        if (status.phase === 'rolled_back' || status.phase === 'failed') {
          updateOutcome = 'rolled_back';
          updateOutcomeDetail = status.detail || null;
          updateApplying = false;
          updatePhaseText = '';
          return;
        }
      } catch (_) {
        // still down / rebuilding — keep polling
      }
    }
    updateOutcome = 'timeout';
    updateApplying = false;
    updatePhaseText = '';
  }

  let devDemo = $derived($gameState.dev_demo);
  let vp = $derived($gameState.voicepack_generation);
  let vpText = $derived.by(() => {
    const s = vp;
    if (!s) return '';
    if (s.running) return `Generating… ${s.done + s.skipped} / ${s.total} (${s.skipped} skipped)`;
    if (s.error) return `Failed: ${s.error}`;
    if (s.total) return `Done — ${s.done} generated, ${s.skipped} skipped.`;
    return '';
  });
</script>

<PageHeader title="Settings" />

{#if banner}
  <div class="settings-banner" class:ok={banner.kind === 'ok'} class:warn={banner.kind === 'warn'} class:error={banner.kind === 'error'}>
    {banner.text}
  </div>
{/if}

<div class="tab-row">
  {#each tabs as t (t.id)}
    <button type="button" class="tab-chip" class:active={activeTab === t.id} onclick={() => (activeTab = t.id)}>
      {t.label}
    </button>
  {/each}
</div>

<form onsubmit={save}>
  {#if activeTab === 'general'}
    <div class="settings-section">
      <div class="settings-section-title">Logging <span class="badge runtime">applies instantly</span></div>
      <div class="settings-row">
        <label for="sLogLevel">Level</label>
        <select id="sLogLevel" bind:value={cfg.logging.level}>
          <option value="DEBUG">DEBUG</option>
          <option value="INFO">INFO</option>
          <option value="WARNING">WARNING</option>
          <option value="ERROR">ERROR</option>
        </select>
      </div>
      <div class="settings-row">
        <label for="sLogEvents">Log events</label>
        <input type="checkbox" id="sLogEvents" bind:checked={cfg.logging.events}>
      </div>
      <div class="settings-row">
        <label for="sLogFile">Log file</label>
        <input type="text" id="sLogFile" placeholder="(none — stderr only)" bind:value={cfg.logging.file}>
      </div>
    </div>

    <div class="settings-section">
      <div class="settings-section-title">Web UI <span class="badge runtime">applies instantly</span></div>
      <div class="settings-row">
        <label for="sWebPort">Port</label>
        <input type="number" id="sWebPort" readonly value={cfg.web.port}>
      </div>
      <p class="note">Port is read-only — changing it would disconnect the current session.</p>
      <div class="settings-row">
        <label for="sWebTheme">Theme</label>
        <select id="sWebTheme" bind:value={cfg.web.theme}>
          <option value="default">Default</option>
          <option value="ocean">Ocean</option>
          <option value="sunset">Sunset</option>
          <option value="forest">Forest</option>
        </select>
      </div>
      <div class="settings-row"><label for="sWebAccent">Custom accent color</label><input type="text" id="sWebAccent" placeholder="#7c6aff (overrides theme)" bind:value={cfg.web.accent_color}></div>
      <div class="settings-row">
        <label for="sWebJoke">Joke of the day</label>
        <input type="checkbox" id="sWebJoke" bind:checked={cfg.web.joke_of_the_day}>
      </div>
      <p class="note">The About page fetches the joke from icanhazdadjoke.com. Switch it off to make no outbound request.</p>
    </div>

    <div class="settings-section">
      <div class="settings-section-title">Statistics <span class="badge restart">restart to apply</span></div>
      <div class="settings-row"><label for="sStatsDb">Database file</label><input type="text" id="sStatsDb" placeholder="stats.db" bind:value={cfg.stats.db}></div>
    </div>
  {:else if activeTab === 'mqtt'}
    <div class="settings-section">
      <div class="settings-section-title">MQTT <span class="badge restart">restart to apply</span></div>
      <p class="note">Fully optional — Elimination, the scoreboard, and the voice caller all work with MQTT off; this only feeds Home Assistant / ESPHome / LED displays.</p>
      <div class="settings-row"><label for="sMqttEnabled">Enabled</label><input type="checkbox" id="sMqttEnabled" bind:checked={cfg.mqtt.enabled}></div>
      <div class="settings-row"><label for="sMqttHost">Host</label><input type="text" id="sMqttHost" placeholder="e.g. 192.168.1.100" bind:value={cfg.mqtt.host}></div>
      <div class="settings-row"><label for="sMqttPort">Port</label><input type="number" id="sMqttPort" min="1" max="65535" placeholder="1883" bind:value={cfg.mqtt.port}></div>
      <div class="settings-row"><label for="sMqttUser">Username</label><input type="text" id="sMqttUser" bind:value={cfg.mqtt.username}></div>
      <div class="settings-row"><label for="sMqttPass">Password</label><input type="password" id="sMqttPass" bind:value={cfg.mqtt.password}></div>
      <div class="settings-row"><label for="sMqttTopic">Base topic</label><input type="text" id="sMqttTopic" placeholder="autodarts" bind:value={cfg.mqtt.base_topic}></div>
    </div>
  {:else if activeTab === 'source'}
    <div class="settings-section">
      <div class="settings-section-title">Source: Direct mode <span class="badge restart">restart to apply</span></div>
      <div class="settings-row"><label for="sDirEmail">Email</label><input type="text" id="sDirEmail" bind:value={cfg.direct.email}></div>
      <div class="settings-row"><label for="sDirPass">Password</label><input type="password" id="sDirPass" bind:value={cfg.direct.password}></div>
      <div class="settings-row"><label for="sDirBoard">Board ID</label><input type="text" id="sDirBoard" bind:value={cfg.direct.board_id}></div>
      <div class="settings-row"><label for="sDirBoardWs">Board WebSocket URL</label><input type="text" id="sDirBoardWs" placeholder="ws://localhost:3180/api/events" bind:value={cfg.direct.board_ws_url}></div>
      <div class="settings-row"><label for="sDirBoardMgr">Board manager URL</label><input type="text" id="sDirBoardMgr" placeholder="(auto-resolved from Autodarts cloud)" bind:value={cfg.direct.board_manager_url}></div>
    </div>
  {:else if activeTab === 'voice'}
    <div class="settings-section">
      <div class="settings-section-title">Voice caller <span class="badge restart">restart to apply</span></div>
      <div class="settings-row"><label for="sAudioDir">Sounds directory</label><input type="text" id="sAudioDir" placeholder="/path/to/sounds" bind:value={cfg.audio.dir}></div>
      <div class="settings-row">
        <label for="sAudioProfile">Voice-pack profile</label>
        <select id="sAudioProfile" bind:value={cfg.audio.profile}>
          <option value="">(own sounds only)</option>
          {#each voicePackProfiles as p}
            <option value={p}>{p}</option>
          {/each}
        </select>
      </div>
      <div class="settings-row"><label for="sCallerEnabled">Caller enabled</label><input type="checkbox" id="sCallerEnabled" bind:checked={cfg.caller.enabled}></div>
      <div class="settings-row"><label for="sCallerPerDart">Call every dart</label><input type="checkbox" id="sCallerPerDart" bind:checked={cfg.caller.per_dart}></div>
      <div class="settings-row"><label for="sCallerMisses">Announce misses ("outside")</label><input type="checkbox" id="sCallerMisses" bind:checked={cfg.caller.call_misses}></div>
      <div class="settings-row"><label for="sCallerTotal">Call turn total</label><input type="checkbox" id="sCallerTotal" bind:checked={cfg.caller.turn_total}></div>
      <div class="settings-row"><label for="sCallerCheckout">Checkout call repeat limit (0 = off)</label><input type="number" id="sCallerCheckout" min="0" step="1" bind:value={cfg.caller.checkout_limit}></div>
      <div class="settings-row"><label for="sCallerChange">Announce player change</label><input type="checkbox" id="sCallerChange" bind:checked={cfg.caller.announce_change}></div>
      <div class="settings-row"><label for="sCallerPlayer">Call player names</label><input type="checkbox" id="sCallerPlayer" bind:checked={cfg.caller.call_player}></div>
      <div class="settings-row"><label for="sCallerAmbient">Ambient volume (0 = off)</label><input type="number" id="sCallerAmbient" min="0" max="1" step="0.1" bind:value={cfg.caller.ambient_volume}></div>
    </div>

    <div class="settings-section">
      <div class="settings-section-title">Voice pack</div>
      <p class="note">Generates any missing sound files for the current voice-pack plan (tools/voicepack_leni.toml) via edge-tts. Check "force" to also re-generate files that already exist — needed after editing existing phrases, takes several minutes for the whole pack.</p>
      <div class="settings-row"><label for="sVoicepackForce">Force full regeneration</label><input type="checkbox" id="sVoicepackForce" bind:checked={voicepackForce}></div>
      <button type="button" class="btn btn-add" style="width:100%" onclick={regenerateVoicepack} disabled={vp?.running}>Regenerate voice pack</button>
      <div class="voicepack-progress">{vpText}</div>
    </div>
  {:else if activeTab === 'voicepack'}
    <div class="settings-section">
      <div class="settings-section-title">Group</div>
      <div class="settings-row">
        <label for="sVpGroup">Group</label>
        <select id="sVpGroup" bind:value={vpSelectedGroup} onchange={onVpGroupChange}>
          {#each vpGroups as g (g.name)}
            <option value={g.name}>{g.name}{g.is_range ? ' (numbers)' : ''}</option>
          {/each}
        </select>
      </div>
    </div>

    <div class="settings-section">
      <div class="settings-section-title">Existing entries{vpEntriesLoading ? ' — loading…' : ''}</div>
      {#if !vpEntries.length && !vpEntriesLoading}
        <p class="note">No entries generated yet in this group.</p>
      {/if}
      {#each vpEntries as entry (entry.key)}
        <div class="vp-entry">
          <div class="vp-entry-header">
            <span class="vp-entry-key">{entry.key}</span>
            <button type="button" class="btn-icon" onclick={() => editVpEntry(entry)}>Edit</button>
          </div>
          {#each entry.variants as v (v.index)}
            <div class="vp-variant-row">
              <span class="vp-variant-text">{v.text}</span>
              <button type="button" class="btn-icon" disabled={!v.has_file}
                      title={v.has_file ? 'Play' : 'Not generated yet'}
                      onclick={() => playVpFile(v.filename)}>▶</button>
              <button type="button" class="btn-icon remove" title="Delete this variant"
                      onclick={() => deleteVpVariant(entry.key, v.index)}>×</button>
            </div>
          {/each}
        </div>
      {/each}
    </div>

    <div class="settings-section">
      <div class="settings-section-title">Add / edit entry</div>
      <p class="note">Key: a player-roster name, a phrase key, or a number (for a numbers group). Add one or more variant texts — spelled however makes the voice say it right — preview each, then save. Saving (re)writes the .mp3 file(s) for this key and updates the plan; an existing key with the same name is replaced entirely.</p>
      <div class="settings-row">
        <label for="sVpKey">Key</label>
        <input type="text" id="sVpKey" bind:value={vpFormKey} placeholder="e.g. peter, close, 21">
      </div>
      {#each vpFormVariants as _, i}
        <div class="vp-variant-row">
          <input type="text" bind:value={vpFormVariants[i]} placeholder="variant text">
          <button type="button" class="btn-icon" onclick={() => previewVpVariant(vpFormVariants[i])}>▶</button>
          <button type="button" class="btn-icon remove" onclick={() => removeVpVariantRow(i)}>×</button>
        </div>
      {/each}
      <button type="button" class="btn btn-add" onclick={addVpVariantRow}>+ Add variant</button>
      <button type="button" class="btn btn-add" style="width:100%; margin-top:0.5rem"
              onclick={saveVpEntry} disabled={vpSaving}>{vpSaving ? 'Saving…' : '💾 Save entry'}</button>
    </div>
  {:else if activeTab === 'dev'}
    <div class="settings-section">
      <div class="settings-section-title">Recording <span class="badge restart">restart to apply</span></div>
      <p class="note">Records every incoming board event to a JSONL file — useful for building a new fixture for the demo below, or for `replay` mode. Only active in direct mode; leave blank to disable.</p>
      <div class="settings-row"><label for="sRecordFile">Recording file</label><input type="text" id="sRecordFile" placeholder="data/sessions/session.jsonl" bind:value={cfg.record.file}></div>
    </div>

    <div class="settings-section">
      <div class="settings-section-title">Simulate a match</div>
      <p class="note">Plays out a full X01 leg or Elimination match at runtime, live on /tv — no physical board needed. Refuses to start while a real match is already in progress.</p>
      <button type="button" class="btn btn-add" style="width:100%" onclick={() => startDemo('x01')} disabled={devDemo?.running}>▶ Simulate X01 leg</button>
      <button type="button" class="btn btn-add" style="width:100%; margin-top:0.5rem" onclick={() => startDemo('elimination')} disabled={devDemo?.running}>▶ Simulate Elimination match</button>
      <div class="voicepack-progress">{devDemo?.running ? `Running… (${devDemo.mode})` : ''}</div>
    </div>
  {/if}

  <button type="submit" class="btn btn-save">Save</button>
</form>

<div class="settings-section maintenance">
  <div class="settings-section-title">Application</div>
  <p class="note">Restarts the whole Breakfast process — needed to apply any "restart to apply" setting above. Relies on the container's restart policy (or your process supervisor) to bring it back up; if you're running it bare (no supervisor), it just stops.</p>
  <button type="button" class="btn btn-stop" style="width:100%" onclick={restartApp}>Restart Breakfast</button>
</div>

<div class="settings-section maintenance">
  <div class="settings-section-title">Updates</div>
  {#if updateApplying}
    <p class="note">{updatePhaseText}</p>
  {:else}
    <button type="button" class="btn btn-add" style="width:100%" onclick={checkForUpdate} disabled={updateChecking}>
      {updateChecking ? 'Checking…' : 'Check for update'}
    </button>

    {#if updateInfo?.error}
      <p class="note update-error">{updateInfo.error}</p>
    {:else if updateInfo?.update_available}
      <p class="note">Version {updateInfo.latest} is available (current: {updateInfo.current}).</p>
      <button type="button" class="btn btn-save" style="width:100%; margin-top:0.5rem" onclick={applyUpdate}>Update now</button>
    {:else if updateInfo}
      <p class="note">Up to date — version {updateInfo.current} is the latest.</p>
    {/if}

    {#if updateOutcome === 'rolled_back'}
      <p class="note update-error">Update failed and was automatically rolled back{updateOutcomeDetail ? `: ${updateOutcomeDetail}` : '.'} Contact whoever maintains this app if it keeps happening.</p>
    {:else if updateOutcome === 'timeout'}
      <p class="note update-error">The app didn't come back after the update. It may still be starting — try reloading in a minute, or contact whoever maintains this app.</p>
    {/if}
  {/if}
</div>

<style>
  .settings-section {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 1rem; margin-bottom: 1rem;
  }
  .settings-section.maintenance { margin-top: 1.5rem; }
  .settings-section-title {
    font-size: 0.75rem; color: var(--muted); font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 0.75rem;
    display: flex; align-items: center; gap: 0.5rem;
  }
  .badge {
    font-size: 0.65rem; padding: 0.1rem 0.45rem; border-radius: 20px;
    text-transform: none; letter-spacing: 0; font-weight: 500;
  }
  .badge.runtime { background: rgba(74,222,128,0.12); color: var(--green); }
  .badge.restart { background: rgba(251,191,36,0.12); color: var(--yellow); }
  .tab-row { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1.25rem; }
  .tab-chip {
    background: var(--surface); border: 1px solid var(--border); color: var(--muted);
    border-radius: 999px; padding: 0.45rem 1rem; font-size: 0.85rem; font-weight: 600;
    font-family: inherit; cursor: pointer; transition: border-color 0.15s, color 0.15s, background 0.15s;
  }
  .tab-chip:hover { border-color: var(--accent); color: var(--text); }
  .tab-chip.active { border-color: var(--accent); color: var(--bg); background: var(--accent); }
  .settings-row {
    display: grid; grid-template-columns: 8rem 1fr; align-items: center;
    gap: 0.5rem; margin-bottom: 0.5rem;
  }
  .settings-row:last-child { margin-bottom: 0; }
  .settings-row label { font-size: 0.85rem; color: var(--muted); }
  .settings-row input[type="text"],
  .settings-row input[type="number"],
  .settings-row input[type="password"] {
    width: 100%; background: var(--bg); border: 1px solid var(--border);
    border-radius: 6px; color: var(--text); padding: 0.35rem 0.6rem; font-size: 0.85rem;
  }
  .settings-row input:focus { outline: none; border-color: var(--accent); }
  .settings-row input[readonly] { opacity: 0.45; cursor: not-allowed; }
  .settings-row select {
    background: var(--bg); border: 1px solid var(--border);
    border-radius: 6px; color: var(--text); padding: 0.35rem 0.6rem; font-size: 0.85rem;
  }
  .note { font-size: 0.75rem; color: var(--muted); margin: 0 0 0.5rem; }
  .note.update-error { color: var(--red); }
  .settings-banner {
    padding: 0.7rem 1rem; border-radius: 8px; border: 1px solid;
    font-size: 0.875rem; margin-bottom: 1rem;
  }
  .settings-banner.ok { background: rgba(74,222,128,0.1); border-color: var(--green); color: var(--green); }
  .settings-banner.warn { background: rgba(251,191,36,0.1); border-color: var(--yellow); color: var(--yellow); }
  .settings-banner.error { background: rgba(248,113,113,0.1); border-color: var(--red); color: var(--red); }
  .btn { border: none; border-radius: 8px; padding: 0.65rem 1.5rem; font-size: 0.95rem; font-weight: 600; cursor: pointer; transition: opacity 0.15s; }
  .btn:hover { opacity: 0.85; }
  .btn:disabled { opacity: 0.4; cursor: default; }
  .btn-save { background: var(--accent); color: #fff; width: 100%; margin-top: 0.5rem; }
  .btn-add { background: var(--surface); border: 1px solid var(--border); color: var(--text); padding: 0.5rem 1rem; }
  .btn-stop { background: #7f1d1d; color: #fff; padding: 0.5rem 1rem; }
  .voicepack-progress { font-size: 0.8rem; color: var(--muted); margin-top: 0.5rem; }
  .vp-entry { border-bottom: 1px solid var(--border); padding: 0.6rem 0; }
  .vp-entry:last-child { border-bottom: none; }
  .vp-entry-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.3rem; }
  .vp-entry-key { font-weight: 600; font-size: 0.9rem; }
  .vp-variant-row { display: flex; align-items: center; gap: 0.4rem; margin-bottom: 0.4rem; }
  .vp-variant-row input[type="text"] {
    flex: 1; background: var(--bg); border: 1px solid var(--border); color: var(--text);
    border-radius: 6px; padding: 0.4rem 0.6rem; font-size: 0.85rem;
  }
  .vp-variant-row input:focus { outline: none; border-color: var(--accent); }
  .vp-variant-text { flex: 1; font-size: 0.85rem; }
  .btn-icon {
    background: var(--bg); border: 1px solid var(--border); color: var(--text);
    border-radius: 6px; padding: 0.3rem 0.6rem; font-size: 0.8rem; cursor: pointer;
    flex-shrink: 0;
  }
  .btn-icon:hover { border-color: var(--accent); color: var(--accent); }
  .btn-icon:disabled { opacity: 0.35; cursor: not-allowed; }
  .btn-icon.remove:hover { border-color: var(--red); color: var(--red); }
</style>
