// The one browser audio player for Breakfast: the /audio page, the TV page
// and the Settings preview all play through it.
//
// It owns a single long-lived AudioContext, so the OS sees one output stream
// for the whole page instead of a new one per sound. A per-sound `Audio`
// element opens and closes its own stream, and the start of the sound is cut
// off while the stream is still being set up.
//
// Voice sounds form a queue that is scheduled on the context clock, so
// consecutive phrases join without a gap. Ambient sounds play on their own
// path and never interrupt voice.

const LEAD = 0.01; // seconds between "now" and the start of a sound
const CACHE_MAX = 300;
// Below one 16-bit step, so the output stays silent, but the graph keeps
// producing samples and the browser keeps the output stream open between calls.
const KEEP_ALIVE_LEVEL = 1e-5;

export function soundUrl(file, v) {
  return '/api/sound/' + encodeURIComponent(file) + (v ? '?v=' + encodeURIComponent(v) : '');
}

function clampVolume(v) {
  return Math.max(0, Math.min(1, v ?? 1));
}

function defaultContext() {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  return new Ctx({ latencyHint: 'interactive' });
}

export function createPlayer({
  contextFactory = defaultContext,
  fetchFn = (...args) => fetch(...args),
  onQueueChange = () => {},
  onError = (msg) => console.warn('[audio] ' + msg),
} = {}) {
  let ctx = null;
  let generation = 0; // bumped by stopVoice(), invalidates queued items
  let voiceEnd = 0; // context time at which the last scheduled voice sound ends
  let tail = Promise.resolve();
  let pending = 0; // voice sounds not yet finished (decoding, scheduled or playing)
  let ambient = null;
  let ambientGen = 0;
  const voiceNodes = new Set();
  const cache = new Map(); // url -> Promise<AudioBuffer>

  function report(msg) {
    try { onError(msg); } catch (_) { /* a failing logger must not stop playback */ }
  }

  function setPending(n) {
    pending = n;
    try { onQueueChange(pending); } catch (_) { /* same */ }
  }

  function ensureContext() {
    if (ctx && ctx.state !== 'closed') return ctx;
    ctx = contextFactory();
    try {
      const keepAlive = ctx.createConstantSource();
      keepAlive.offset.value = KEEP_ALIVE_LEVEL;
      keepAlive.connect(ctx.destination);
      keepAlive.start();
    } catch (e) {
      report('keep-alive source unavailable: ' + (e.message || e));
    }
    return ctx;
  }

  async function ensureRunning() {
    const c = ensureContext();
    if (c.state === 'running') return c;
    try {
      await c.resume();
    } catch (e) {
      report('audio context could not resume: ' + (e.message || e));
    }
    if (c.state !== 'running') report('audio context is ' + c.state + ', sound may be silent');
    return c;
  }

  // Call from a user gesture: browsers block audio until the page was clicked.
  function unlock() {
    const c = ensureContext();
    if (c.state === 'suspended') {
      c.resume().catch((e) => report('audio context could not resume: ' + (e.message || e)));
    }
    // A one-sample silent buffer also unlocks browsers that need a played sound.
    try {
      const src = c.createBufferSource();
      src.buffer = c.createBuffer(1, 1, 22050);
      src.connect(c.destination);
      src.start(0);
    } catch (_) { /* the resume above is what counts */ }
  }

  function load(url) {
    let p = cache.get(url);
    if (p) {
      cache.delete(url);
      cache.set(url, p);
      return p;
    }
    const c = ensureContext();
    p = fetchFn(url)
      .then((r) => {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.arrayBuffer();
      })
      .then((data) => c.decodeAudioData(data));
    p.catch(() => cache.delete(url));
    cache.set(url, p);
    if (cache.size > CACHE_MAX) cache.delete(cache.keys().next().value);
    return p;
  }

  function release(node) {
    try { node.src.disconnect(); } catch (_) { /* already gone */ }
    try { node.gain.disconnect(); } catch (_) { /* already gone */ }
  }

  function connect(c, buffer, volume) {
    const src = c.createBufferSource();
    src.buffer = buffer;
    const gain = c.createGain();
    gain.gain.value = clampVolume(volume);
    src.connect(gain);
    gain.connect(c.destination);
    return { src, gain };
  }

  function stopVoice() {
    generation += 1;
    for (const node of voiceNodes) {
      node.src.onended = null;
      try { node.src.stop(); } catch (_) { /* never started */ }
      release(node);
    }
    voiceNodes.clear();
    voiceEnd = 0;
    setPending(0);
  }

  function stopAmbient() {
    ambientGen += 1;
    if (!ambient) return;
    ambient.src.onended = null;
    try { ambient.src.stop(); } catch (_) { /* never started */ }
    release(ambient);
    ambient = null;
  }

  function enqueueVoice(inst) {
    if (inst.break_last) stopVoice();
    const gen = generation;
    // Fetch and decode start now, so the phrases of a batch load in parallel.
    const decoded = load(soundUrl(inst.file, inst.v));
    decoded.catch(() => {}); // handled in the queue below
    setPending(pending + 1);
    const finish = () => { if (gen === generation) setPending(Math.max(0, pending - 1)); };

    tail = tail.then(async () => {
      try {
        let buffer;
        try {
          buffer = await decoded;
        } catch (e) {
          report(inst.file + ': ' + (e.message || e));
          finish();
          return;
        }
        if (gen !== generation) return;
        const c = await ensureRunning();
        if (gen !== generation) return;
        const node = connect(c, buffer, inst.volume);
        const start = Math.max(c.currentTime + LEAD, voiceEnd);
        voiceEnd = start + buffer.duration;
        voiceNodes.add(node);
        node.src.onended = () => {
          voiceNodes.delete(node);
          release(node);
          finish();
        };
        node.src.start(start);
      } catch (e) {
        report(inst.file + ': ' + (e.message || e));
        finish();
      }
    });
  }

  function playAmbient(inst) {
    stopAmbient();
    const gen = ambientGen;
    load(soundUrl(inst.file, inst.v))
      .then(async (buffer) => {
        if (gen !== ambientGen) return;
        const c = await ensureRunning();
        if (gen !== ambientGen) return;
        const node = connect(c, buffer, inst.volume);
        ambient = node;
        node.src.onended = () => {
          release(node);
          if (ambient === node) ambient = null;
        };
        node.src.start(c.currentTime + LEAD);
      })
      .catch((e) => report(inst.file + ': ' + (e.message || e)));
  }

  // One play instruction from the server: {file, v, channel, volume, break_last}.
  function handle(inst) {
    if (inst.channel === 'ambient') playAmbient(inst);
    else enqueueVoice(inst);
  }

  // A sound that is not part of the queue, e.g. a preview: encoded audio bytes.
  async function playData(data, volume = 1) {
    const c = await ensureRunning();
    const buffer = await c.decodeAudioData(data);
    const node = connect(c, buffer, volume);
    node.src.onended = () => release(node);
    node.src.start(c.currentTime + LEAD);
  }

  function stopAll() {
    stopVoice();
    stopAmbient();
  }

  return { unlock, handle, playData, stopVoice, stopAmbient, stopAll };
}
