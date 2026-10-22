<script>
  import { confirmDialog, alertDialog } from '../../lib/confirm.js';
  import { t } from '../../lib/i18n.js';
  // The settings page: config form (logging/mqtt/stats/web/direct/audio/caller), the look, voice-pack
  // regeneration and editing, updates and the Restart button. Grouped into tabs (Appearance, Audio & Voice with
  // its sub-tabs, Connections, System, Dev); the address is #settings/<tab>[/<sub-tab>]. Save stays below the
  // tab content and saves the whole config regardless of which tab is showing.
  import { onMount, tick } from 'svelte';
  import { route, navigate, openTv } from '../../lib/router.js';
  import { pendingRestart } from '../../lib/stores/pendingRestart.js';
  import { applyAuroraColors, applyLook, auroraAnimated, loadAppearance } from '../../lib/stores/appearance.js';
  import ColorField from '../../lib/components/ColorField.svelte';
  import { gameState } from '../../lib/stores/gameState.js';
  import { api } from '../../lib/api.js';
  import PageHeader from '../../lib/components/PageHeader.svelte';
  import WhatsNew from '../../lib/components/WhatsNew.svelte';
  import { health } from '../../lib/stores/health.js';
  import { changesOf } from '../../lib/changelog.js';
  import AchievementSounds from './AchievementSounds.svelte';
  import LocationsSection from './LocationsSection.svelte';
  import CircleSection from './CircleSection.svelte';
  import { createPlayer } from '../../lib/audioPlayer.js';

  const MASK = '●●●●●';
  const emptyCfg = () => ({
    logging: { level: 'INFO', events: false, file: '' },
    mqtt: { enabled: true, host: '', port: '', username: '', password: '', base_topic: '' },
    stats: { db: '', timezone: '' },
    web: { port: '', accent_color: '', language: 'en', aurora_animation: true,
           aurora_base: '', aurora_1: '', aurora_2: '', aurora_3: '',
           aurora_palette: '', aurora_streaks: true, aurora_speed: 100, aurora_intensity: 100, aurora_blur: 100,
           aurora_pause_idle: 0, glass_strength: 100, bar_opacity: 92 },
    direct: { email: '', password: '', board_id: '', board_ws_url: '', board_manager_url: '' },
    audio: { dir: '', profile: '' },
    caller: {
      enabled: true, per_dart: true, turn_total: true, checkout_limit: 1,
      announce_change: true, call_player: true, ambient_volume: 0.6, call_misses: true,
    },
    record: { file: '' },
    online: { relay_url: '', site_name: '' },
    telemetry: { enabled: false, url: '' },
    updates: { check: true, auto_install: false },
    // Read-only — not part of the editable form/save flow, set directly in
    // config.toml. Only gates whether the Dev tab below is shown at all.
    dev: { enabled: false },
  });

  const TABS = [
    { id: 'appearance', label: t('Appearance') },
    { id: 'audio', label: t('Audio & Voice') },
    { id: 'connections', label: t('Connections') },
    { id: 'system', label: t('System') },
  ];
  const AUDIO_TABS = [
    { id: 'caller', label: t('Caller') },
    { id: 'voicepack', label: t('Voice Pack') },
    { id: 'achievements', label: t('Achievements') },
  ];
  let tabs = $derived(cfg.dev?.enabled ? [...TABS, { id: 'dev', label: t('Dev') }] : TABS);
  let address = $derived($route.split('/'));   // ['settings', tab, sub-tab]
  let activeTab = $derived(tabs.some((tk) => tk.id === address[1]) ? address[1] : 'appearance');
  let audioTab = $derived(AUDIO_TABS.some((tk) => tk.id === address[2]) ? address[2] : 'caller');
  const openTab = (id) => navigate(id === 'appearance' ? 'settings' : 'settings/' + id);
  const openAudioTab = (id) => navigate('settings/audio/' + id);

  let cfg = $state(emptyCfg());
  let voicePackProfiles = $state([]);
  // Snapshot of what was actually loaded from config.toml, so save() can
  // tell "field is empty because it was never set" apart from "field was
  // cleared just now" — only the latter should send an explicit null to
  // actually remove the key (see save()'s addIfChanged()).
  let loadedCfg = emptyCfg();
  let banner = $state(null); // { kind: 'ok'|'warn'|'error', text }
  // Set when the time zone field was filled from this browser because none is configured.
  let timezoneSuggested = $state(false);
  let voicepackForce = $state(false);

  // Voice Pack tab — add/edit/browse/delete individual voice-pack entries,
  // separate from the whole-pack "Regenerate" flow above and from the
  // shared config Save (this tab writes the plan of the selected pack in tools/ + sound
  // files directly, not config.toml).
  let vpPacks = $state([]);
  let vpPack = $state('');
  let vpGroups = $state([]);
  let vpSelectedGroup = $state('');
  let vpEntries = $state([]);
  let vpEntriesLoading = $state(false);
  let vpFormKey = $state('');
  let vpFormVariants = $state(['']);
  let vpSaving = $state(false);

  onMount(async () => {
    await loadConfig();
    await loadAppearance();
    lookTick += 1;
    await loadVoicePackProfiles();
    await loadVoicepackPacks();
    await loadVoicepackGroups();
    await loadDbBackup();
    await loadPort();
  });

  // The packs that have a plan file, and the one to start on (the active profile if it has a plan).
  async function loadVoicepackPacks() {
    try {
      const res = await fetch('/api/voicepack/packs').then((r) => r.json());
      vpPacks = res.packs || [];
      vpPack = res.default || '';
    } catch (e) {
      console.error('loadVoicepackPacks failed:', e);
    }
  }

  const packQuery = () => (vpPack ? '&pack=' + encodeURIComponent(vpPack) : '');
  let vpPlan = $derived(vpPacks.find((p) => p.name === vpPack)?.plan || '');

  async function onVpPackChange() {
    vpSelectedGroup = '';
    vpEntries = [];
    resetVpForm();
    await loadVoicepackGroups();
  }

  async function loadVoicepackGroups() {
    try {
      const res = await fetch('/api/voicepack/groups?' + packQuery().slice(1)).then((r) => r.json());
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
      const res = await fetch('/api/voicepack/entries?group=' + encodeURIComponent(vpSelectedGroup) + packQuery())
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

  const previewPlayer = createPlayer();

  async function playAudioBlobResponse(res) {
    const ct = res.headers.get('content-type') || '';
    if (!res.ok || !ct.includes('audio')) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || `HTTP ${res.status}`);
    }
    await previewPlayer.playData(await res.arrayBuffer());
  }

  async function previewVpVariant(text) {
    if (!text.trim()) return;
    try {
      const res = await fetch('/api/voicepack/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ group: vpSelectedGroup, text, pack: vpPack || null }),
      });
      await playAudioBlobResponse(res);
    } catch (e) {
      alertDialog(t('Preview failed: {error}', { error: e.message }));
    }
  }

  async function playVpFile(filename) {
    try {
      await playAudioBlobResponse(await fetch('/api/voicepack/file/' + encodeURIComponent(filename) + '?' + packQuery().slice(1)));
    } catch (e) {
      alertDialog(t('Playback failed: {error}', { error: e.message }));
    }
  }

  async function saveVpEntry() {
    const key = vpFormKey.trim();
    const variants = vpFormVariants.map((v) => v.trim()).filter(Boolean);
    if (!key || !variants.length) {
      alertDialog(t('Key and at least one variant are required.'));
      return;
    }
    vpSaving = true;
    try {
      const res = await fetch('/api/voicepack/entries', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ group: vpSelectedGroup, key, variants, pack: vpPack || null }),
      }).then((r) => r.json());
      if (res.error) { alertDialog(t('Save failed: {error}', { error: t(res.error) })); return; }
      resetVpForm();
      await loadVoicepackEntries();
    } catch (e) {
      alertDialog(t('Save failed: {error}', { error: e }));
    } finally {
      vpSaving = false;
    }
  }

  async function deleteVpVariant(key, index) {
    if (!await confirmDialog(t('Delete this variant?'))) return;
    try {
      const res = await fetch('/api/voicepack/entries', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ group: vpSelectedGroup, key, variant_index: index, pack: vpPack || null }),
      }).then((r) => r.json());
      if (res.error) { alertDialog(t('Delete failed: {error}', { error: t(res.error) })); return; }
      await loadVoicepackEntries();
    } catch (e) {
      alertDialog(t('Delete failed: {error}', { error: e }));
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

  // What usage reporting would send and what it sent lately, for the "Show what is sent" panel.
  let reportPreview = $state(null);
  async function toggleReportPreview() {
    if (reportPreview) { reportPreview = null; return; }
    try {
      reportPreview = await fetch('/api/telemetry').then((r) => r.json());
    } catch (e) {
      console.error('loadReportPreview failed:', e);
    }
  }

  // The report address starts as the relay address (empty in the file means the same) and follows it while it is not
  // typed over; it is saved as empty again when it equals the relay address.
  let reportFollowsRelay = $state(true);
  $effect(() => {
    if (reportFollowsRelay) cfg.telemetry.url = cfg.online.relay_url || '';
  });

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
      reportFollowsRelay = !fresh.telemetry.url || fresh.telemetry.url === fresh.online.relay_url;
      if (!reportFollowsRelay) cfg.telemetry.url = fresh.telemetry.url;
      if (!cfg.stats.timezone) {
        // Nothing configured: suggest the zone of this browser, saved like any other change.
        cfg.stats.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
        timezoneSuggested = !!cfg.stats.timezone;
      }
    } catch (e) {
      console.error('loadConfig failed:', e);
    }
  }

  // The look (aurora and glass): a change made here shows at once (a preview) and is stored with Save.
  const AURORA_COLORS = [
    { key: 'aurora_base', label: t('Base') }, { key: 'aurora_1', label: t('Color 1') },
    { key: 'aurora_2', label: t('Color 2') }, { key: 'aurora_3', label: t('Color 3') },
  ];
  const PALETTES = [
    ['ocean', t('Ocean')], ['sunset', t('Sunset')], ['forest', t('Forest')], ['northern', t('Northern lights')], ['ember', t('Ember')], ['lavender', t('Lavender')],
    ['graphite', t('Graphite')], ['sakura', t('Sakura')],
  ];
  // [key, label, lowest, highest, step, default]
  const LOOK_SLIDERS = [
    ['aurora_speed', t('Speed'), 25, 300, 5, 100], ['aurora_intensity', t('Intensity'), 30, 115, 5, 100],
    ['aurora_blur', t('Softness'), 30, 200, 5, 100], ['glass_strength', t('Glass strength'), 50, 200, 5, 100],
    ['bar_opacity', t('Top bar opacity'), 50, 100, 1, 92],
  ];
  const LOOK_DEFAULTS = { aurora_animation: true, aurora_streaks: true, aurora_palette: '', aurora_pause_idle: 0,
    ...Object.fromEntries(LOOK_SLIDERS.map(([key, , , , , def]) => [key, def])) };
  const GLASS_KEYS = ['glass_strength', 'bar_opacity'];
  const GLASS_SLIDERS = LOOK_SLIDERS.filter(([key]) => GLASS_KEYS.includes(key));
  const AURORA_SLIDERS = LOOK_SLIDERS.filter(([key]) => !GLASS_KEYS.includes(key));
  let lookTick = $state(0);   // moves on every preview, so the swatches show the color the palette gives
  const presetColor = (key) => getComputedStyle(document.documentElement).getPropertyValue('--' + key.replace('_', '-')).trim() || '#000000';
  function previewLook() {
    const w = cfg.web;
    applyLook({ palette: w.aurora_palette, speed: Number(w.aurora_speed), intensity: Number(w.aurora_intensity),
                blur: Number(w.aurora_blur), glass: Number(w.glass_strength), bar: Number(w.bar_opacity),
                streaks: w.aurora_streaks, pause_idle: Number(w.aurora_pause_idle) });
    applyAuroraColors({ base: w.aurora_base, 1: w.aurora_1, 2: w.aurora_2, 3: w.aurora_3 });
    auroraAnimated.set(w.aurora_animation);
    lookTick += 1;
  }
  // A palette replaces the colors picked before, otherwise a picked color would hide it.
  function choosePalette() {
    for (const { key } of AURORA_COLORS) cfg.web[key] = '';
    previewLook();
  }
  function resetLook() {
    for (const { key } of AURORA_COLORS) cfg.web[key] = '';
    Object.assign(cfg.web, LOOK_DEFAULTS);
    previewLook();
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
    addIfChanged('stats', 'timezone', cfg.stats.timezone);
    addIfChanged('direct', 'email', cfg.direct.email);
    addIfChanged('direct', 'password', cfg.direct.password);
    addIfChanged('direct', 'board_id', cfg.direct.board_id);
    addIfChanged('direct', 'board_ws_url', cfg.direct.board_ws_url);
    addIfChanged('direct', 'board_manager_url', cfg.direct.board_manager_url);
    addIfChanged('audio', 'dir', cfg.audio.dir);
    addIfChanged('audio', 'profile', cfg.audio.profile);
    addIfChanged('web', 'accent_color', cfg.web.accent_color);
    for (const { key } of AURORA_COLORS) addIfChanged('web', key, cfg.web[key]);
    for (const key of ['aurora_palette', 'aurora_streaks', 'aurora_pause_idle', ...LOOK_SLIDERS.map((x) => x[0])]) {
      const value = typeof LOOK_DEFAULTS[key] === 'number' ? Number(cfg.web[key]) : cfg.web[key];
      (updates.web ??= {})[key] = value === LOOK_DEFAULTS[key] ? null : value;   // a default is not written to the file
    }
    addIfChanged('record', 'file', cfg.record.file);
    addIfChanged('online', 'relay_url', cfg.online.relay_url);
    addIfChanged('online', 'site_name', cfg.online.site_name);
    const reportUrl = cfg.telemetry.url === cfg.online.relay_url ? '' : cfg.telemetry.url;
    addIfChanged('telemetry', 'url', reportUrl);
    addIfChanged('mqtt', 'port', cfg.mqtt.port, (v) => parseInt(v, 10));
    if (portInfo?.mode === 'config') addIfChanged('web', 'port', cfg.web.port, (v) => parseInt(v, 10));
    addIfChanged('caller', 'checkout_limit', cfg.caller.checkout_limit, (v) => parseInt(v, 10));
    addIfChanged('caller', 'ambient_volume', cfg.caller.ambient_volume, (v) => parseFloat(v));

    // Selects and checkboxes — always a concrete value, sent when it differs from the loaded one.
    const addIfDiffers = (section, key, val) => {
      if (val !== loadedCfg[section]?.[key]) (updates[section] ??= {})[key] = val;
    };
    addIfDiffers('logging', 'level', cfg.logging.level);
    addIfDiffers('web', 'language', cfg.web.language);
    addIfDiffers('logging', 'events', cfg.logging.events);
    addIfDiffers('mqtt', 'enabled', cfg.mqtt.enabled);
    addIfDiffers('telemetry', 'enabled', cfg.telemetry.enabled);
    addIfDiffers('updates', 'check', cfg.updates.check);
    addIfDiffers('updates', 'auto_install', cfg.updates.auto_install);
    addIfDiffers('web', 'joke_of_the_day', cfg.web.joke_of_the_day);
    addIfDiffers('web', 'aurora_animation', cfg.web.aurora_animation);
    for (const key of ['enabled', 'per_dart', 'turn_total', 'announce_change', 'call_player', 'call_misses']) {
      addIfDiffers('caller', key, cfg.caller[key]);
    }

    try {
      const res = await fetch('/api/config', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      }).then((r) => r.json());
      if (res.saved && cfg.web.language !== loadedCfg.web.language) {
        location.reload(); // every text is translated once at start
        return;
      }
      showBanner(res);
      if (res.saved) {
        loadedCfg = JSON.parse(JSON.stringify(cfg));
        loadedCfg.telemetry.url = reportUrl;
        timezoneSuggested = false;
      }
      await loadAppearance();
      lookTick += 1;
    } catch (err) {
      alertDialog(t('Save failed: {error}', { error: err }));
    }
  }

  // What a setting is called in the notice that asks for a restart (the config key as `section.key`).
  const KEY_LABELS = {
    'logging.file': t('Log file'), 'logging.events': t('Log events'),
    'mqtt.enabled': t('MQTT enabled'), 'mqtt.host': t('MQTT host'), 'mqtt.port': t('MQTT port'),
    'mqtt.username': t('MQTT username'), 'mqtt.password': t('MQTT password'), 'mqtt.base_topic': t('MQTT base topic'),
    'stats.db': t('Database file'), 'stats.timezone': t('Time zone'),
    'direct.email': t('Email'), 'direct.password': t('Board data source password'), 'direct.board_id': t('Board ID'),
    'direct.board_ws_url': t('Board WebSocket URL'), 'direct.board_manager_url': t('Board manager URL'),
    'audio.dir': t('Sounds directory'), 'audio.profile': t('Voice Profile'),
    'caller.enabled': t('Caller enabled'), 'caller.per_dart': t('Call every dart'),
    'caller.turn_total': t('Call turn total'), 'caller.checkout_limit': t('Repeat same Checkout limit'),
    'caller.announce_change': t('Call player change'), 'caller.call_player': t('Call player names'),
    'caller.ambient_volume': t('Ambient volume (0 = off)'), 'caller.call_misses': t('Call a Miss'),
    'record.file': t('Recording file'), 'web.port': t('Web UI port'),
  };
  const labelOf = (key) => KEY_LABELS[key] ?? key;

  function showBanner(res) {
    if (!res.saved) {
      banner = { kind: 'error', text: res.error ? t('Save failed: {error}', { error: t(res.error) }) : t('Save failed.') };
    } else {
      // A restart notice stays until it is dismissed or the app was restarted, see the banner below the heading.
      if (res.restart_required?.length) pendingRestart.update((keys) => [...new Set([...keys, ...res.restart_required])]);
      banner = { kind: 'ok', text: $pendingRestart.length ? t('Saved.') : t('Saved. Changes applied immediately.') };
    }
    setTimeout(() => { banner = null; }, 8000);
  }

  async function regenerateVoicepack() {
    if (voicepackForce && !await confirmDialog(t('Regenerate the ENTIRE voice pack? This can take several minutes.'))) return;
    const res = await api('POST', '/api/voicepack/generate', { force: voicepackForce, pack: vpPack || null })
      .then(() => ({}))
      .catch((err) => ({ error: String(err) }));
    if (res && res.error) alertDialog(t('Could not start: {error}', { error: t(res.error) }));
  }

  async function startDemo(mode) {
    // Not using the shared api() helper here — it discards the response
    // body, but the backend's "already running" / "real match in progress"
    // guard messages (returned as {started:false, error} with a 200 status)
    // are exactly what's useful to show the user for this action.
    const res = await fetch(`/api/dev/demo/${mode}`, { method: 'POST' })
      .then((r) => r.json())
      .catch((err) => ({ started: false, error: String(err) }));
    if (!res?.started) alertDialog(t('Could not start demo: {error}', { error: (res?.error ? t(res.error) : t('unknown error')) }));
  }

  // What a restart or an update does to the game in play: a match of X01, Elimination or Killer is saved and offered
  // again afterwards, any other game is lost.
  function runningNote() {
    const game = $gameState.running_game;
    if (!game) return '';
    return ' ' + (game.resumable ? t('The running game will be saved.') : t('The running game will be lost.'));
  }

  // The newest copy of the statistics database that an update took before it started.
  let dbBackup = $state(null);

  async function loadDbBackup() {
    try {
      dbBackup = (await fetch('/api/updates/backup').then((r) => r.json())).backup;
    } catch (_) { /* nothing shown */ }
  }

  let whatsNew = $state(null);

  async function showWhatsNew() {
    const changes = await changesOf($health.version);
    if (changes?.sections.length) whatsNew = changes;
    else alertDialog(t('No changes are listed for this version.'));
  }

  async function showUpdates() {
    navigate('settings/system');
    await tick();
    document.getElementById('updates-panel')?.scrollIntoView({ behavior: 'smooth' });
  }

  async function restartApp() {
    if (!await confirmDialog(t('Restart Breakfast?') + runningNote())) return;
    await api('POST', '/api/control/restart');
    pendingRestart.set([]);
    // A port saved outside Docker is taken at the start: this page moves to it.
    const port = Number(loadedCfg.web.port);
    if (portInfo?.mode === 'config' && port && port !== (Number(location.port) || 80)) await waitForPort(port);
  }

  // The web UI port. In Docker the updater service publishes it (`.env`) and recreates the container, elsewhere it is
  // `[web] port` of the config, saved with the form and taken at the next restart.
  let portInfo = $state(null);        // { mode: 'docker' | 'config', port, supported?, phase?, detail?, error? }
  let portInput = $state('');
  let portApplying = $state(false);

  async function loadPort() {
    try {
      portInfo = await fetch('/api/web-port').then((r) => r.json());
      portInput = portInfo.port ?? '';
    } catch (_) { /* the Dev tab shows nothing */ }
  }

  const PORT_MESSAGES = {
    in_use: (port) => t('Port {port} is already in use on this machine.', { port }),
    unsupported: () => t('This installation has no port setting yet. Install the latest update first.'),
    busy: () => t('An update or a port change is already in progress.'),
    same: () => t('That port is already set.'),
    invalid: () => t('The port must be a number from 1024 to 65535.'),
  };

  // Waits until Breakfast answers on *port* of this host, then opens the page there.
  async function waitForPort(port) {
    portApplying = true;
    const origin = `${location.protocol}//${location.hostname}:${port}`;
    const deadline = Date.now() + 3 * 60 * 1000;
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 2000));
      try {
        await fetch(`${origin}/api/health`, { mode: 'no-cors' });
        location.href = `${origin}/#settings/dev`;
        return;
      } catch (_) { /* not up yet */ }
    }
    portApplying = false;
    alertDialog(t('Breakfast did not answer on port {port}. If the change failed, the old port is still in use.', { port }));
  }

  async function applyPort() {
    const port = Number(portInput);
    if (!Number.isInteger(port) || port < 1024 || port > 65535) {
      alertDialog(PORT_MESSAGES.invalid());
      return;
    }
    if (!await confirmDialog(t('Move Breakfast to port {port}? The container restarts and this page opens at the new address.', { port }) + runningNote())) return;
    const res = await fetch('/api/web-port', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ port }),
    }).then((r) => r.json()).catch((err) => ({ ok: false, error: String(err) }));
    if (!res.ok) {
      alertDialog(PORT_MESSAGES[res.code]?.(port) ?? t('Could not change the port: {error}', { error: res.error || t('unknown error') }));
      return;
    }
    await waitForPort(port);
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
    if (!await confirmDialog(t('Install update to v{latest}?', { latest: updateInfo.latest }) + runningNote())) return;
    const res = await fetch('/api/updates/apply', { method: 'POST' })
      .then((r) => r.json())
      .catch((e) => ({ error: String(e) }));
    if (res.error || res.ok === false) {
      alertDialog(t('Could not start the update: {error}', { error: (res.error ? t(res.error) : t('unknown error')) }));
      return;
    }
    updateApplying = true;
    updateOutcome = null;
    updateOutcomeDetail = null;
    updatePhaseText = t('Installing update — this can take a few minutes…');
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
    if (s.running) return t('Generating… {done} / {total} ({skipped} skipped)', { done: s.done + s.skipped, total: s.total, skipped: s.skipped });
    if (s.error) return t('Failed: {error}', { error: s.error });
    if (s.total) return t('Done — {done} generated, {skipped} skipped.', { done: s.done, skipped: s.skipped });
    return '';
  });
</script>
<PageHeader title={t('Settings')} />

{#if $gameState.running_game}
  <a class="back-to-game" href="#tv" onclick={openTv}>← {t('Back to game')}</a>
{/if}

{#if banner}
  <div class="settings-banner" class:ok={banner.kind === 'ok'} class:warn={banner.kind === 'warn'} class:error={banner.kind === 'error'}>
    {banner.text}
  </div>
{/if}

{#if $pendingRestart.length}
  <div class="settings-banner warn restart-banner">
    <span>{t('Restart required to apply: {settings}', { settings: $pendingRestart.map(labelOf).join(', ') })}</span>
    <button type="button" class="btn btn-stop" onclick={restartApp}>{t('Restart Breakfast')}</button>
    <button type="button" class="btn-icon" title={t('Dismiss')} aria-label={t('Dismiss')} onclick={() => pendingRestart.set([])}>×</button>
  </div>
{/if}

{#if $gameState.update?.available}
  <button type="button" class="update-chip" onclick={showUpdates}>{t('v{version} available', { version: $gameState.update.latest })}</button>
{/if}

<div class="tab-row">
  {#each tabs as tk (tk.id)}
    <button type="button" class="tab-chip" class:active={activeTab === tk.id} onclick={() => openTab(tk.id)}>
      {tk.label}
    </button>
  {/each}
</div>

{#if activeTab === 'audio'}
  <div class="tab-row sub">
    {#each AUDIO_TABS as tk (tk.id)}
      <button type="button" class="tab-chip" class:active={audioTab === tk.id} onclick={() => openAudioTab(tk.id)}>
        {tk.label}
      </button>
    {/each}
  </div>
{/if}

{#if activeTab === 'audio' && audioTab === 'achievements'}
  <AchievementSounds />
{/if}

<form onsubmit={save} hidden={activeTab === 'audio' && audioTab === 'achievements'}>
  {#if activeTab === 'appearance'}
    <div class="settings-section">
      <div class="settings-section-title">{t('Display')}</div>
      <div class="settings-row">
        <label for="sWebLanguage">{t('Language')}</label>
        <select id="sWebLanguage" bind:value={cfg.web.language}>
          <option value="en">{t('English')}</option>
          <option value="de">{t('Deutsch')}</option>
        </select>
      </div>
      <div class="settings-row">
        <label for="sWebJoke">{t('Joke of the day')}</label>
        <input type="checkbox" id="sWebJoke" bind:checked={cfg.web.joke_of_the_day}>
      </div>
    </div>

    <div class="settings-section look">
      <div class="settings-section-title">{t('Theme')}</div>
      <div class="settings-section-title sub">{t('Glass')}</div>
      {#each GLASS_SLIDERS as [key, label, low, high, step]}
        <div class="settings-row">
          <label for={'s_' + key}>{label}</label>
          <span class="range-pair">
            <input type="range" id={'s_' + key} min={low} max={high} {step} bind:value={cfg.web[key]} oninput={previewLook}>
            <output>{cfg.web[key]} %</output>
          </span>
        </div>
      {/each}

      <div class="settings-section-title sub">{t('Aurora')}</div>
      <div class="settings-row">
        <label for="sWebAurora">{t('Animate the background')}</label>
        <input type="checkbox" id="sWebAurora" bind:checked={cfg.web.aurora_animation} onchange={previewLook}>
      </div>
      <div class="settings-row">
        <label for="sLookStreaks">{t('Streaks')}</label>
        <input type="checkbox" id="sLookStreaks" bind:checked={cfg.web.aurora_streaks} onchange={previewLook}>
      </div>
      {#each AURORA_SLIDERS as [key, label, low, high, step]}
        <div class="settings-row">
          <label for={'s_' + key}>{label}</label>
          <span class="range-pair">
            <input type="range" id={'s_' + key} min={low} max={high} {step} bind:value={cfg.web[key]} oninput={previewLook}>
            <output>{cfg.web[key]} %</output>
          </span>
        </div>
      {/each}
      <div class="settings-row">
        <label for="sLookIdle">{t('Pause after (minutes)')}</label>
        <input type="number" id="sLookIdle" min="0" max="240" bind:value={cfg.web.aurora_pause_idle} oninput={previewLook}>
      </div>
      <p class="note">{t('Saves power: the aurora also stops while the page is hidden. With a number of minutes it stops after that long without a key or mouse movement and moves again on the next one; 0 never stops it.')}</p>

      <div class="settings-section-title sub">{t('Palette and colors')}</div>
      <div class="settings-row">
        <label for="sLookPalette">{t('Palette')}</label>
        <select id="sLookPalette" bind:value={cfg.web.aurora_palette} onchange={choosePalette}>
          <option value="">{t('Default')}</option>
          {#each PALETTES as [id, name] (id)}
            <option value={id}>{name}</option>
          {/each}
        </select>
      </div>
      <div class="aurora-colors">
        {#each AURORA_COLORS as c (c.key)}
          <div class="settings-row">
            <label for={'s_' + c.key}>{c.label}</label>
            <ColorField id={'s_' + c.key} label={c.label} value={cfg.web[c.key]} fallback={presetColor(c.key, lookTick)}
                        onchange={(v) => { cfg.web[c.key] = v; previewLook(); }} />
          </div>
        {/each}
      </div>
      <div class="settings-row"><label for="sWebAccent">{t('Custom accent color')}</label><input type="text" id="sWebAccent" placeholder="#FFFFFF" bind:value={cfg.web.accent_color}></div>
      <button type="button" class="btn btn-add" onclick={resetLook}>{t('Reset')}</button>
    </div>

  {:else if activeTab === 'audio'}
    {#if audioTab === 'caller'}
      <div class="settings-section">
        <div class="settings-section-title">{t('Voice pack')}</div>
        {#if vpPacks.length}
          <div class="settings-row">
            <label for="sVpPackGen">{t('Pack')}</label>
            <select id="sVpPackGen" bind:value={vpPack} onchange={onVpPackChange}>
              {#each vpPacks as pk (pk.name)}
                <option value={pk.name}>{pk.name} ({pk.voice})</option>
              {/each}
            </select>
          </div>
        {/if}
        <div class="settings-row"><label for="sVoicepackForce">{t('Force full regeneration')}</label><input type="checkbox" id="sVoicepackForce" bind:checked={voicepackForce}></div>
        <button type="button" class="btn btn-add" style="width:100%" onclick={regenerateVoicepack} disabled={vp?.running || !vpPack}>{t('Regenerate voice pack')}</button>
        <p class="note">{t('Generates any missing sound files for the voice-pack')}</p>
        <div class="voicepack-progress">{vpText}</div>
      </div>

      <div class="settings-section">
        <div class="settings-section-title">{t('Voice caller')} <span class="badge restart">{t('needs a restart')}</span></div>
        <div class="settings-row"><label for="sAudioDir">{t('Sounds directory')}</label><input type="text" id="sAudioDir" placeholder={t('/path/to/sounds')} bind:value={cfg.audio.dir}></div>
        <div class="settings-row">
          <label for="sAudioProfile">{t('Voice Profile')}</label>
          <select id="sAudioProfile" bind:value={cfg.audio.profile}>
            <option value="">{t('(own sounds only)')}</option>
            {#each voicePackProfiles as p}
              <option value={p}>{p}</option>
            {/each}
          </select>
        </div>
        <div class="settings-row"><label for="sCallerEnabled">{t('Caller enabled')}</label><input type="checkbox" id="sCallerEnabled" bind:checked={cfg.caller.enabled}></div>
        <div class="settings-row"><label for="sCallerPerDart">{t('Call every dart')}</label><input type="checkbox" id="sCallerPerDart" bind:checked={cfg.caller.per_dart}></div>
        <div class="settings-row"><label for="sCallerMisses">{t('Call a Miss')}</label><input type="checkbox" id="sCallerMisses" bind:checked={cfg.caller.call_misses}></div>
        <div class="settings-row"><label for="sCallerTotal">{t('Call turn total')}</label><input type="checkbox" id="sCallerTotal" bind:checked={cfg.caller.turn_total}></div>
        <div class="settings-row"><label for="sCallerCheckout">{t('Repeat same Checkout limit')}</label><input type="number" id="sCallerCheckout" min="0" step="1" bind:value={cfg.caller.checkout_limit}></div>
        <div class="settings-row"><label for="sCallerChange">{t('Call player change')}</label><input type="checkbox" id="sCallerChange" bind:checked={cfg.caller.announce_change}></div>
        <div class="settings-row"><label for="sCallerPlayer">{t('Call player names')}</label><input type="checkbox" id="sCallerPlayer" bind:checked={cfg.caller.call_player}></div>
        <div class="settings-row"><label for="sCallerAmbient">{t('Ambient volume (0 = off)')}</label><input type="number" id="sCallerAmbient" min="0" max="1" step="0.1" bind:value={cfg.caller.ambient_volume}></div>
      </div>
    {:else if audioTab === 'voicepack'}
      <div class="settings-section">
        <div class="settings-section-title">{t('Pack')}</div>
        {#if vpPacks.length}
          <div class="settings-row">
            <label for="sVpPack">{t('Pack')}</label>
            <select id="sVpPack" bind:value={vpPack} onchange={onVpPackChange}>
              {#each vpPacks as pk (pk.name)}
                <option value={pk.name}>{pk.name} ({pk.voice})</option>
              {/each}
            </select>
          </div>
          <p class="note">{t('Edits the plan {plan}. A downloaded pack without a plan file is not listed.', { plan: 'tools/' + vpPlan })}</p>
        {:else}
          <p class="note">{t('No voice-pack plan found.')}</p>
        {/if}
      </div>

      <div class="settings-section">
        <div class="settings-section-title">{t('Group')}</div>
        <div class="settings-row">
          <label for="sVpGroup">{t('Group')}</label>
          <select id="sVpGroup" bind:value={vpSelectedGroup} onchange={onVpGroupChange}>
            {#each vpGroups as g (g.name)}
              <option value={g.name}>{g.name}{g.is_range ? ' ' + t('(numbers)') : ''}</option>
            {/each}
          </select>
        </div>
      </div>

      <div class="settings-section">
        <div class="settings-section-title">{t('Add / edit entry')}</div>
        <p class="note">{t('Key: a player-roster name, a phrase key, or a number (for a numbers group). Add one or more variant texts — spelled however makes the voice say it right — preview each, then save. Saving (re)writes the .mp3 file(s) for this key and updates the plan; an existing key with the same name is replaced entirely.')}</p>
        <div class="settings-row">
          <label for="sVpKey">{t('Key')}</label>
          <input type="text" id="sVpKey" bind:value={vpFormKey} placeholder={t('e.g. peter, close, 21')}>
        </div>
        {#each vpFormVariants as _, i}
          <div class="vp-variant-row">
            <input type="text" bind:value={vpFormVariants[i]} placeholder={t('variant text')}>
            <button type="button" class="btn-icon" onclick={() => previewVpVariant(vpFormVariants[i])}>▶</button>
            <button type="button" class="btn-icon remove" onclick={() => removeVpVariantRow(i)}>×</button>
          </div>
        {/each}
        <button type="button" class="btn btn-add" onclick={addVpVariantRow}>{t('+ Add variant')}</button>
        <button type="button" class="btn btn-add" style="width:100%; margin-top:0.5rem"
                onclick={saveVpEntry} disabled={vpSaving}>{vpSaving ? t('Saving…') : t('💾 Save entry')}</button>
      </div>

      <div class="settings-section">
        <div class="settings-section-title">{t('Existing entries')}{vpEntriesLoading ? ' — ' + t('Loading…') : ''}</div>
        {#if !vpEntries.length && !vpEntriesLoading}
          <p class="note">{t('No entries generated yet in this group.')}</p>
        {/if}
        {#each vpEntries as entry (entry.key)}
          <div class="vp-entry">
            <div class="vp-entry-header">
              <span class="vp-entry-key">{entry.key}</span>
              <button type="button" class="btn-icon" onclick={() => editVpEntry(entry)}>{t('Edit')}</button>
            </div>
            {#each entry.variants as v (v.index)}
              <div class="vp-variant-row">
                <span class="vp-variant-text">{v.text}</span>
                <button type="button" class="btn-icon" disabled={!v.has_file}
                        title={v.has_file ? t('Play variant') : t('Not generated yet')}
                        onclick={() => playVpFile(v.filename)}>▶</button>
                <button type="button" class="btn-icon remove" title={t('Delete this variant')}
                        onclick={() => deleteVpVariant(entry.key, v.index)}>×</button>
              </div>
            {/each}
          </div>
        {/each}
      </div>
    {/if}
  {:else if activeTab === 'connections'}
    <div class="settings-section">
      <div class="settings-section-title">{t('Board data source')} <span class="badge restart">{t('needs a restart')}</span></div>
      <div class="settings-row"><label for="sDirEmail">{t('Email')}</label><input type="text" id="sDirEmail" bind:value={cfg.direct.email}></div>
      <div class="settings-row"><label for="sDirPass">{t('Password')}</label><input type="password" id="sDirPass" bind:value={cfg.direct.password}></div>
      <div class="settings-row"><label for="sDirBoard">{t('Board ID')}</label><input type="text" id="sDirBoard" bind:value={cfg.direct.board_id}></div>
      <div class="settings-row"><label for="sDirBoardWs">{t('Board WebSocket URL')}</label><input type="text" id="sDirBoardWs" placeholder={t('ws://localhost:3180/api/events')} bind:value={cfg.direct.board_ws_url}></div>
      <div class="settings-row"><label for="sDirBoardMgr">{t('Board manager URL')}</label><input type="text" id="sDirBoardMgr" placeholder={t('(auto-resolved from Autodarts cloud)')} bind:value={cfg.direct.board_manager_url}></div>
    </div>

    <div class="settings-section">
      <div class="settings-section-title">{t('MQTT')} <span class="badge restart">{t('needs a restart')}</span></div>
      <p class="note">{t('Optional - feeds Home Assistant / ESPHome / LED displays.')}</p>
      <div class="settings-row"><label for="sMqttEnabled">{t('Enabled')}</label><input type="checkbox" id="sMqttEnabled" bind:checked={cfg.mqtt.enabled}></div>
      <div class="settings-row"><label for="sMqttHost">{t('Host')}</label><input type="text" id="sMqttHost" placeholder="e.g. 192.168.1.100" bind:value={cfg.mqtt.host}></div>
      <div class="settings-row"><label for="sMqttPort">{t('Port')}</label><input type="number" id="sMqttPort" min="1" max="65535" placeholder="1883" bind:value={cfg.mqtt.port}></div>
      <div class="settings-row"><label for="sMqttUser">{t('Username')}</label><input type="text" id="sMqttUser" bind:value={cfg.mqtt.username}></div>
      <div class="settings-row"><label for="sMqttPass">{t('Password')}</label><input type="password" id="sMqttPass" bind:value={cfg.mqtt.password}></div>
      <div class="settings-row"><label for="sMqttTopic">{t('Base topic')}</label><input type="text" id="sMqttTopic" placeholder={t('autodarts')} bind:value={cfg.mqtt.base_topic}></div>
    </div>

    <div class="settings-section">
      <div class="settings-section-title">{t('Online Elimination')}</div>
      <div class="settings-row"><label for="sOnlineRelay">{t('Relay address')}</label><input type="text" id="sOnlineRelay" placeholder={t('wss://breakfast-relay.example.workers.dev')} bind:value={cfg.online.relay_url}></div>
      <div class="settings-row"><label for="sOnlineSite">{t('This site\'s name')}</label><input type="text" id="sOnlineSite" placeholder={t('e.g. Home')} maxlength="24" bind:value={cfg.online.site_name}></div>
    </div>

    <LocationsSection />
    <CircleSection />
  {:else if activeTab === 'system'}
    <div class="settings-section" id="updates-panel">
      <div class="settings-section-title">{t('Updates')}</div>
      <div class="settings-row">
        <label for="sUpdateCheck">{t('Look for a new release every day')}</label>
        <input type="checkbox" id="sUpdateCheck" bind:checked={cfg.updates.check}>
      </div>
      <div class="settings-row">
        <label for="sAutoInstall">{t('Install updates automatically')}</label>
        <input type="checkbox" id="sAutoInstall" bind:checked={cfg.updates.auto_install} disabled={!cfg.updates.check}>
      </div>
      <p class="note">{t('Installs a newer patch or minor release after the start and at 04:00, never while a game is running. A new major version is only announced.')}</p>
      {#if updateApplying}
        <p class="note">{updatePhaseText}</p>
      {:else}
        <button type="button" class="btn btn-add" style="width:100%; margin-top:0.5rem" onclick={checkForUpdate} disabled={updateChecking}>
          {updateChecking ? t('Checking…') : t('Check for update')}
        </button>

        {#if updateInfo?.error}
          <p class="note update-error">{updateInfo.error}</p>
        {:else if updateInfo?.update_available}
          <p class="note">{t('Version {latest} is available (current: {current}).', { latest: updateInfo.latest, current: updateInfo.current })}</p>
          <button type="button" class="btn btn-save" style="width:100%; margin-top:0.5rem" onclick={applyUpdate}>{t('Update now')}</button>
        {:else if updateInfo}
          <p class="note">{t('Up to date — version {current} is the latest.', { current: updateInfo.current })}</p>
        {/if}

        {#if dbBackup}
          <p class="note">{t('Last backup of the statistics: v{version}, {time}', { version: dbBackup.version, time: new Date(dbBackup.at).toLocaleString() })}</p>
        {/if}

        <button type="button" class="btn btn-add" style="width:100%; margin-top:0.5rem" onclick={showWhatsNew}>{t("What's new in this version")}</button>

        {#if updateOutcome === 'rolled_back'}
          <p class="note update-error">{t('Update failed and was automatically rolled back')}{updateOutcomeDetail ? `: ${updateOutcomeDetail}` : '.'} {t('Contact whoever maintains this app if it keeps happening.')}</p>
        {:else if updateOutcome === 'timeout'}
          <p class="note update-error">{t('The app didn\'t come back after the update. It may still be starting — try reloading in a minute, or contact whoever maintains this app.')}</p>
        {/if}
      {/if}
    </div>

    <div class="settings-section">
      <div class="settings-section-title">{t('Usage reports')}</div>
      <div class="settings-row">
        <label for="sTelemetryOn">{t('Send anonymous usage and error reports')}</label>
        <input type="checkbox" id="sTelemetryOn" bind:checked={cfg.telemetry.enabled}>
      </div>
      <div class="settings-row"><label for="sTelemetryUrl">{t('Report address')}</label><input type="text" id="sTelemetryUrl" bind:value={cfg.telemetry.url} oninput={() => (reportFollowsRelay = false)}></div>
      <p class="note">{t('Off by default. Sends the version, the platform, the game modes played with their duration and the errors that occur, under a random installation ID. No player names, scores or addresses.')}</p>
      <button type="button" class="btn btn-add" onclick={toggleReportPreview}>{reportPreview ? t('Hide') : t('Show what is sent')}</button>
      {#if reportPreview}
        <p class="note">{t('Installation ID')}: {reportPreview.install_id || t('Not created yet')}</p>
        <p class="note">{t('Waiting to be sent')}</p>
        <pre class="report-preview">{reportPreview.queued.length ? JSON.stringify(reportPreview.queued, null, 1) : t('Nothing')}</pre>
        <p class="note">{t('Sent lately')}</p>
        <pre class="report-preview">{reportPreview.sent.length ? JSON.stringify(reportPreview.sent, null, 1) : t('Nothing')}</pre>
      {/if}
    </div>

    <div class="settings-section">
      <div class="settings-section-title">{t('Statistics')} <span class="badge restart">{t('needs a restart')}</span></div>
      <div class="settings-row"><label for="sStatsDb">{t('Database file')}</label><input type="text" id="sStatsDb" placeholder={t('stats.db')} bind:value={cfg.stats.db}></div>
      <div class="settings-row"><label for="sStatsTimezone">{t('Time zone')}</label><input type="text" id="sStatsTimezone" placeholder={t('UTC')} bind:value={cfg.stats.timezone} oninput={() => (timezoneSuggested = false)}></div>
      {#if timezoneSuggested}
        <p class="note">{t('No time zone is set, so UTC applies. This one is taken from your browser: save to use it.')}</p>
      {:else}
        <p class="note">{t('An IANA name such as Europe/Zurich. It sets the local days and hours used for achievements.')}</p>
      {/if}
    </div>
  {:else if activeTab === 'dev'}
    <div class="settings-section">
      <div class="settings-section-title">{t('Logging')}</div>
      <div class="settings-row">
        <label for="sLogLevel">{t('Level')}</label>
        <select id="sLogLevel" bind:value={cfg.logging.level}>
          <option value="DEBUG">{t('DEBUG')}</option>
          <option value="INFO">{t('INFO')}</option>
          <option value="WARNING">{t('WARNING')}</option>
          <option value="ERROR">{t('ERROR')}</option>
        </select>
      </div>
      <div class="settings-row">
        <label for="sLogEvents">{t('Log events')}</label>
        <input type="checkbox" id="sLogEvents" bind:checked={cfg.logging.events}>
      </div>
      <div class="settings-row">
        <label for="sLogFile">{t('Log file')}</label>
        <input type="text" id="sLogFile" placeholder={t('(none — stderr only)')} bind:value={cfg.logging.file}>
      </div>
    </div>

    <div class="settings-section">
      <div class="settings-section-title">{t('Web UI port')} {#if portInfo?.mode === 'config'}<span class="badge restart">{t('needs a restart')}</span>{/if}</div>
      {#if !portInfo}
        <p class="note">{t('Loading…')}</p>
      {:else if portInfo.mode === 'docker'}
        {#if portInfo.error}
          <p class="note update-error">{portInfo.error}</p>
        {:else if !portInfo.supported}
          <p class="note">{t('This installation has no port setting yet. Install the latest update first.')}</p>
        {:else}
          <div class="settings-row">
            <label for="sWebPort">{t('Port')}</label>
            <input type="number" id="sWebPort" min="1024" max="65535" bind:value={portInput}>
          </div>
          <p class="note">{t('The port Breakfast is published on at this machine. Inside the container it stays on 8080.')}</p>
          {#if portInfo.phase === 'failed'}
            <p class="note update-error">{t('The last port change failed: {detail}', { detail: portInfo.detail || t('unknown error') })}</p>
          {/if}
          <button type="button" class="btn btn-add" onclick={applyPort}
                  disabled={portApplying || !!$gameState.running_game || Number(portInput) === portInfo.port}>
            {portApplying ? t('Waiting for the new port…') : t('Apply port')}
          </button>
          {#if $gameState.running_game}<p class="note">{t('Not available while a game is running.')}</p>{/if}
        {/if}
      {:else}
        <div class="settings-row">
          <label for="sWebPort">{t('Port')}</label>
          <input type="number" id="sWebPort" min="1024" max="65535" bind:value={cfg.web.port}>
        </div>
        <p class="note">{t('Saved with the form and taken at the next restart.')}</p>
      {/if}
      <p class="note">{t('Changing the port moves this page to a new address. Bookmarks, the TV and other devices need the new one.')}</p>
    </div>

    <div class="settings-section">
      <div class="settings-section-title">{t('Recording')} <span class="badge restart">{t('needs a restart')}</span></div>
      <p class="note">{t('Records every incoming board event to a JSONL file — useful for building a new fixture for the demo below, or for `replay` mode. Only active in direct mode; leave blank to disable.')}</p>
      <div class="settings-row"><label for="sRecordFile">{t('Recording file')}</label><input type="text" id="sRecordFile" placeholder={t('data/sessions/session.jsonl')} bind:value={cfg.record.file}></div>
    </div>

    <div class="settings-section">
      <div class="settings-section-title">{t('Simulate a match')}</div>
      <p class="note">{t('Plays out a full X01 leg or Elimination match at runtime, live on the TV view — no physical board needed. Refuses to start while a real match is already in progress.')}</p>
      <button type="button" class="btn btn-add" style="width:100%" onclick={() => startDemo('x01')} disabled={devDemo?.running || !!$gameState.running_game}>{t('▶ Simulate X01 leg')}</button>
      <button type="button" class="btn btn-add" style="width:100%; margin-top:0.5rem" onclick={() => startDemo('elimination')} disabled={devDemo?.running || !!$gameState.running_game}>{t('▶ Simulate Elimination match')}</button>
      {#if $gameState.running_game}<p class="note">{t('Not available while a game is running.')}</p>{/if}
      <div class="voicepack-progress">{devDemo?.running ? t('Running… ({mode})', { mode: devDemo.mode }) : ''}</div>
    </div>
  {/if}

  <button type="submit" class="btn btn-save">{t('Save')}</button>
</form>

{#if activeTab === 'system'}
<div class="settings-section maintenance">
  <div class="settings-section-title">{t('Application')}</div>
  <button type="button" class="btn btn-stop" style="width:100%" onclick={restartApp}>{t('Restart Breakfast')}</button>
</div>
{/if}

{#if whatsNew}
  <WhatsNew changes={whatsNew} onclose={() => (whatsNew = null)} />
{/if}

<style>
  .settings-section {
    background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur);
    border-radius: 16px; padding: 1.25rem 1.4rem; margin-bottom: 1.25rem;
  }
  .settings-section.maintenance { margin-top: 1.5rem; }
  .settings-section-title.sub { margin-top: 1.4rem; }
  .settings-section-title.sub:first-child { margin-top: 0; }
  .back-to-game {
    display: inline-block; margin-bottom: 1rem; padding: 0.45rem 1rem; border-radius: 999px; border: 1px solid var(--accent);
    background: var(--glass); color: var(--accent); font-size: 0.9rem; font-weight: 600; text-decoration: none;
  }
  .back-to-game:hover { background: var(--accent); color: #0c0c0f; }
  .settings-section-title {
    font-size: 0.78rem; color: var(--muted); font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 1rem;
    display: flex; align-items: center; gap: 0.5rem;
  }
  .badge {
    font-size: 0.65rem; padding: 0.1rem 0.45rem; border-radius: 20px;
    text-transform: none; letter-spacing: 0; font-weight: 500;
  }
  .badge.restart { background: rgba(251,191,36,0.12); color: var(--yellow); }
  .tab-row { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1.25rem; }
  .tab-row.sub { margin-top: -0.5rem; }
  .tab-chip {
    background: var(--glass); border: 1px solid var(--glass-border); color: var(--muted); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2);
    border-radius: 999px; padding: 0.45rem 1.1rem; font-size: 0.85rem; font-weight: 600;
    font-family: inherit; cursor: pointer; transition: border-color 0.15s, color 0.15s, background 0.15s;
  }
  .tab-chip:hover { border-color: var(--accent); color: var(--text); }
  .tab-chip.active { border-color: var(--accent); color: #0c0c0f; background: var(--accent); box-shadow: 0 0 16px -4px var(--accent); }
  .settings-row {
    display: grid; grid-template-columns: 8rem 1fr; align-items: center;
    gap: 0.5rem; margin-bottom: 0.65rem;
  }
  .settings-row:last-child { margin-bottom: 0; }
  .settings-row label { font-size: 0.9rem; color: color-mix(in srgb, var(--text) 72%, transparent); }
  .settings-row input[type="text"],
  .settings-row input[type="number"],
  .settings-row input[type="password"] {
    width: 100%; background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border);
    border-radius: 10px; color: var(--text); padding: 0.45rem 0.75rem; font-size: 0.9rem; font-family: inherit;
  }
  .settings-row input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 25%, transparent); }
  .settings-row input[readonly] { opacity: 0.45; cursor: not-allowed; }
  .settings-row input[type="checkbox"] { justify-self: end; width: 1.2rem; height: 1.2rem; accent-color: var(--accent); cursor: pointer; }
  .settings-row select {
    background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border);
    border-radius: 10px; color: var(--text); padding: 0.45rem 0.75rem; font-size: 0.9rem; font-family: inherit;
  }
  .note { font-size: 0.75rem; color: var(--muted); margin: 0 0 0.5rem; }
  .report-preview { font-size: 0.7rem; max-height: 12rem; overflow: auto; margin: 0 0 0.5rem; padding: 0.5rem; border-radius: 0.5rem; background: rgba(0, 0, 0, 0.25); white-space: pre-wrap; word-break: break-all; }
  .note.update-error { color: var(--red); }
  .update-chip {
    margin-bottom: 1rem; padding: 0.45rem 1rem; border-radius: 999px; border: 1px solid var(--accent); background: var(--glass);
    color: var(--accent); font: inherit; font-size: 0.9rem; font-weight: 600; cursor: pointer;
  }
  .update-chip:hover { background: var(--accent); color: #0c0c0f; }
  .settings-banner {
    padding: 0.7rem 1rem; border-radius: 8px; border: 1px solid;
    font-size: 0.875rem; margin-bottom: 1rem;
  }
  .settings-banner.ok { background: rgba(74,222,128,0.1); border-color: var(--green); color: var(--green); }
  .settings-banner.warn { background: rgba(251,191,36,0.1); border-color: var(--yellow); color: var(--yellow); }
  .settings-banner.error { background: rgba(248,113,113,0.1); border-color: var(--red); color: var(--red); }
  .restart-banner { display: flex; align-items: center; gap: 0.75rem; }
  .restart-banner span { flex: 1; }
  .btn { border: none; border-radius: 12px; padding: 0.7rem 1.5rem; font-size: 0.95rem; font-weight: 600; cursor: pointer; transition: opacity 0.15s; }
  .btn:hover { opacity: 0.85; }
  .btn:disabled { opacity: 0.4; cursor: default; }
  .btn-save { background: var(--accent); color: #0c0c0f; width: 100%; margin-top: 0.5rem; }
  .btn-add { background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); padding: 0.5rem 1rem; }
  .btn-stop { background: #7f1d1d; color: #fff; padding: 0.5rem 1rem; }
  .aurora-colors { margin: 0.4rem 0 0.2rem; }
  .range-pair { display: flex; align-items: center; gap: 0.8rem; flex: 1; }
  .range-pair input[type="range"] { flex: 1; accent-color: var(--accent); cursor: pointer; }
  .range-pair output { width: 3.6rem; text-align: right; font-size: 0.85rem; color: var(--muted); }
  .aurora-colors .settings-row { align-items: start; }
  .aurora-colors .settings-row label { padding-top: 0.5rem; }
  .voicepack-progress { font-size: 0.8rem; color: var(--muted); margin-top: 0.5rem; }
  .vp-entry { border-bottom: 1px solid var(--glass-border); padding: 0.6rem 0; }
  .vp-entry:last-child { border-bottom: none; }
  .vp-entry-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.3rem; }
  .vp-entry-key { font-weight: 600; font-size: 0.9rem; }
  .vp-variant-row { display: flex; align-items: center; gap: 0.4rem; margin-bottom: 0.4rem; }
  .vp-variant-row input[type="text"] {
    flex: 1; background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); color: var(--text);
    border-radius: 10px; padding: 0.45rem 0.75rem; font-size: 0.9rem; font-family: inherit;
  }
  .vp-variant-row input:focus { outline: none; border-color: var(--accent); }
  .vp-variant-text { flex: 1; font-size: 0.85rem; }
  .btn-icon {
    background: var(--glass); border: 1px solid var(--glass-border); color: var(--text);
    border-radius: 10px; padding: 0.3rem 0.7rem; font-size: 0.8rem; cursor: pointer; font-family: inherit;
    flex-shrink: 0;
  }
  .btn-icon:hover { border-color: var(--accent); color: var(--accent); }
  .btn-icon:disabled { opacity: 0.35; cursor: not-allowed; }
  .btn-icon.remove:hover { border-color: var(--red); color: var(--red); }
</style>