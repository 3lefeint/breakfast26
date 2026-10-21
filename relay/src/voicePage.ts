// The voice chat page the relay serves at /voice (HTML) and /voice.js. It lives on the relay's own HTTPS address
// because browsers give the microphone only to secure pages, which the installations (plain HTTP in a LAN) are not.
// Everything it needs is in its address after the `#` (match code, site, voice ticket, language), which never
// reaches a server. No external libraries. Inside the script strings: no backticks, no dollar-brace, no backslashes.

export const VOICE_HTML = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Breakfast voice chat</title>
<style>
  :root { color-scheme: dark; --bg: #0c0c0f; --card: #17181d; --line: #2a2c35; --text: #e8e8ee; --muted: #8b8d99; --accent: #8bc34a; --red: #ef5350; }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text); font-family: system-ui, sans-serif; min-height: 100vh; display: flex; justify-content: center; padding: 1.5rem 1rem; }
  main { width: 100%; max-width: 30rem; }
  h1 { font-size: 1.3rem; margin: 0 0 0.2rem; }
  .sub { color: var(--muted); margin: 0 0 1.25rem; font-size: 0.9rem; }
  label { display: block; color: var(--muted); font-size: 0.8rem; margin-bottom: 0.3rem; }
  select { width: 100%; background: var(--card); color: var(--text); border: 1px solid var(--line); border-radius: 10px; padding: 0.55rem 0.7rem; font: inherit; margin-bottom: 1rem; }
  .row { display: flex; gap: 0.6rem; flex-wrap: wrap; margin-bottom: 1rem; }
  button { background: var(--card); color: var(--text); border: 1px solid var(--line); border-radius: 999px; padding: 0.6rem 1.2rem; font: inherit; font-weight: 600; cursor: pointer; }
  button:hover:not(:disabled) { border-color: var(--accent); }
  button:disabled { opacity: 0.4; cursor: default; }
  button.primary { background: #166534; border-color: transparent; }
  button.on { border-color: var(--red); color: var(--red); }
  .meter { height: 8px; border-radius: 4px; background: var(--card); border: 1px solid var(--line); overflow: hidden; margin-bottom: 1.25rem; }
  .meter div { height: 100%; width: 0; background: var(--accent); transition: width 0.08s; }
  ul { list-style: none; margin: 0 0 1rem; padding: 0; display: flex; flex-direction: column; gap: 0.4rem; }
  li { display: flex; align-items: center; gap: 0.6rem; background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 0.55rem 0.8rem; }
  li.speaking { border-color: var(--accent); }
  .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--muted); }
  li[data-state="connected"] .dot { background: var(--accent); }
  li[data-state="failed"] .dot { background: var(--red); }
  li .tag { margin-left: auto; color: var(--muted); font-size: 0.8rem; }
  .status { color: var(--muted); font-size: 0.85rem; min-height: 1.2rem; }
  .status.err { color: var(--red); }
</style>
</head>
<body>
<main>
  <h1 id="title"></h1>
  <p class="sub" id="sub"></p>
  <label id="micLabel" for="mic"></label>
  <select id="mic"></select>
  <div class="row">
    <button id="join" class="primary"></button>
    <button id="mute" disabled></button>
    <button id="leave" disabled></button>
  </div>
  <div class="meter"><div id="level"></div></div>
  <ul id="peers"></ul>
  <p class="status" id="status" role="status"></p>
</main>
<script src="/voice.js"></script>
</body>
</html>
`;

export const VOICE_JS = `(function () {
  "use strict";
  var TEXT = {
    en: { title: "Voice chat", sub: "Match {code}, you are {site}", mic: "Microphone", join: "Join voice chat", mute: "Mute", unmute: "Unmute", leave: "Leave",
      you: "you", muted: "muted", nobody: "Nobody else is here yet.", connecting: "Connecting…", connected: "In the voice chat. Keep this tab open while you play.",
      reconnecting: "Connection lost, reconnecting…", nomic: "The microphone is not available. Allow it for this page and try again.", badlink: "This link is incomplete. Open the voice chat from Breakfast again.",
      denied: "Not allowed. Open the voice chat from Breakfast again.", full: "The voice chat is full.", replaced: "You joined from another tab, this one is closed.", left: "You left the voice chat.", headset: "A headset avoids echo." },
    de: { title: "Sprachchat", sub: "Match {code}, du bist {site}", mic: "Mikrofon", join: "Sprachchat beitreten", mute: "Stumm", unmute: "Ton an", leave: "Verlassen",
      you: "du", muted: "stumm", nobody: "Noch niemand sonst da.", connecting: "Verbinde…", connected: "Im Sprachchat. Lass diesen Tab beim Spielen offen.",
      reconnecting: "Verbindung verloren, verbinde neu…", nomic: "Das Mikrofon ist nicht verfügbar. Erlaube es für diese Seite und versuche es noch einmal.", badlink: "Dieser Link ist unvollständig. Öffne den Sprachchat noch einmal in Breakfast.",
      denied: "Kein Zutritt. Öffne den Sprachchat noch einmal in Breakfast.", full: "Der Sprachchat ist voll.", replaced: "Du bist von einem anderen Tab beigetreten, dieser wird geschlossen.", left: "Du hast den Sprachchat verlassen.", headset: "Ein Headset vermeidet Echo." }
  };
  var params = new URLSearchParams(location.hash.slice(1));
  var code = params.get("code"), site = params.get("site"), ticket = params.get("ticket");
  var T = TEXT[params.get("lang") === "de" ? "de" : "en"];
  var $ = function (id) { return document.getElementById(id); };
  var ws = null, me = null, stream = null, ice = [], peers = {}, muted = false, joined = false, leaving = false, audioCtx = null;
  var levels = { me: 0 };

  function status(text, bad) { $("status").textContent = text || ""; $("status").className = "status" + (bad ? " err" : ""); }
  function send(frame) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(frame)); }

  $("title").textContent = T.title;
  $("sub").textContent = T.sub.replace("{code}", code || "?").replace("{site}", site || "?");
  $("micLabel").textContent = T.mic;
  $("join").textContent = T.join;
  $("mute").textContent = T.mute;
  $("leave").textContent = T.leave;
  if (!code || !site || !ticket) { $("join").disabled = true; status(T.badlink, true); }
  else status(T.headset);

  window.__voice = { peers: peers };

  // ── levels ────────────────────────────────────────────────────────────────
  function watch(mediaStream, onLevel) {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    var analyser = audioCtx.createAnalyser();
    analyser.fftSize = 512;
    audioCtx.createMediaStreamSource(mediaStream).connect(analyser);
    var data = new Uint8Array(analyser.fftSize);
    var timer = setInterval(function () {
      analyser.getByteTimeDomainData(data);
      var sum = 0;
      for (var i = 0; i < data.length; i++) { var v = (data[i] - 128) / 128; sum += v * v; }
      onLevel(Math.min(1, Math.sqrt(sum / data.length) * 4));
    }, 100);
    return function () { clearInterval(timer); };
  }

  // ── list of people ────────────────────────────────────────────────────────
  function render() {
    var list = $("peers");
    list.textContent = "";
    var rows = [{ id: "me", name: site, state: "connected", muted: muted, mine: true, level: levels.me }];
    Object.keys(peers).forEach(function (id) { var p = peers[id]; rows.push({ id: id, name: p.name, state: p.pc.connectionState, muted: p.muted, level: p.level }); });
    rows.forEach(function (r) {
      var li = document.createElement("li");
      li.setAttribute("data-state", r.state);
      if (r.level > 0.12 && !r.muted) li.className = "speaking";
      var dot = document.createElement("span"); dot.className = "dot";
      var name = document.createElement("span"); name.textContent = r.name;
      var tag = document.createElement("span"); tag.className = "tag";
      tag.textContent = (r.mine ? T.you : "") + (r.muted ? (r.mine ? ", " : "") + T.muted : "");
      li.appendChild(dot); li.appendChild(name); li.appendChild(tag);
      list.appendChild(li);
    });
    if (joined && Object.keys(peers).length === 0) { var none = document.createElement("li"); none.textContent = T.nobody; list.appendChild(none); }
  }

  // ── microphone ────────────────────────────────────────────────────────────
  function constraints() {
    var device = $("mic").value;
    return { audio: { deviceId: device ? { exact: device } : undefined, echoCancellation: true, noiseSuppression: true, autoGainControl: true } };
  }

  function listMics(selected) {
    return navigator.mediaDevices.enumerateDevices().then(function (devices) {
      var select = $("mic");
      select.textContent = "";
      devices.filter(function (d) { return d.kind === "audioinput"; }).forEach(function (d, i) {
        var o = document.createElement("option"); o.value = d.deviceId; o.textContent = d.label || (T.mic + " " + (i + 1));
        if (d.deviceId === selected) o.selected = true;
        select.appendChild(o);
      });
    });
  }

  var stopMeter = null;
  function useStream(next) {
    var old = stream;
    stream = next;
    stream.getAudioTracks().forEach(function (t) { t.enabled = !muted; });
    if (stopMeter) stopMeter();
    stopMeter = watch(stream, function (v) { levels.me = muted ? 0 : v; $("level").style.width = Math.round(levels.me * 100) + "%"; render(); });
    Object.keys(peers).forEach(function (id) {
      peers[id].pc.getSenders().forEach(function (s) { if (s.track && s.track.kind === "audio") s.replaceTrack(stream.getAudioTracks()[0]); });
    });
    if (old) old.getTracks().forEach(function (t) { t.stop(); });
  }

  $("mic").addEventListener("change", function () {
    if (!joined) return;
    navigator.mediaDevices.getUserMedia(constraints()).then(useStream).catch(function () { status(T.nomic, true); });
  });

  // ── peers ─────────────────────────────────────────────────────────────────
  function addPeer(id, name, initiator) {
    if (peers[id]) return peers[id];
    var pc = new RTCPeerConnection({ iceServers: ice });
    var entry = { pc: pc, name: name, muted: false, level: 0, chain: Promise.resolve(), stop: null, el: null };
    peers[id] = entry;
    stream.getAudioTracks().forEach(function (t) { pc.addTrack(t, stream); });
    pc.onicecandidate = function (e) { if (e.candidate) send({ type: "signal", to: id, data: { candidate: e.candidate } }); };
    pc.onconnectionstatechange = render;
    pc.ontrack = function (e) {
      if (entry.el) return;
      entry.el = new Audio();
      entry.el.autoplay = true;
      entry.el.srcObject = e.streams[0];
      entry.el.play().catch(function () {});
      entry.stop = watch(e.streams[0], function (v) { entry.level = v; render(); });
    };
    if (initiator) {
      pc.createOffer().then(function (o) { return pc.setLocalDescription(o); })
        .then(function () { send({ type: "signal", to: id, data: { description: pc.localDescription } }); });
    }
    render();
    return entry;
  }

  function dropPeer(id) {
    var p = peers[id];
    if (!p) return;
    if (p.stop) p.stop();
    if (p.el) p.el.srcObject = null;
    p.pc.close();
    delete peers[id];
    render();
  }

  function dropAll() { Object.keys(peers).forEach(dropPeer); }

  function onSignal(from, data) {
    var p = peers[from] || addPeer(from, "?", false);
    p.chain = p.chain.then(function () {
      if (data.description) {
        return p.pc.setRemoteDescription(data.description).then(function () {
          if (data.description.type !== "offer") return null;
          return p.pc.createAnswer().then(function (a) { return p.pc.setLocalDescription(a); })
            .then(function () { send({ type: "signal", to: from, data: { description: p.pc.localDescription } }); });
        });
      }
      if (data.candidate) return p.pc.addIceCandidate(data.candidate);
      return null;
    }).catch(function () {});
  }

  // ── the room ──────────────────────────────────────────────────────────────
  function connect() {
    ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/voice/" + code);
    ws.onopen = function () { send({ type: "join", site: site, ticket: ticket }); };
    ws.onmessage = function (ev) {
      var m;
      try { m = JSON.parse(ev.data); } catch (e) { return; }
      if (m.type === "joined") {
        me = m.peer; ice = m.ice || []; joined = true;
        status(T.connected);
        $("mute").disabled = false; $("leave").disabled = false;
        m.peers.forEach(function (p) { addPeer(p.peer, p.site, true); peers[p.peer].muted = !!p.muted; });
        render();
      } else if (m.type === "peer-joined") { addPeer(m.peer, m.site, false); }
      else if (m.type === "peer-left") { dropPeer(m.peer); }
      else if (m.type === "signal") { onSignal(m.from, m.data); }
      else if (m.type === "mute") { if (peers[m.peer]) { peers[m.peer].muted = m.muted; render(); } }
      else if (m.type === "error") { status(m.code === 4409 && /full/.test(m.message) ? T.full : (m.code === 4409 ? T.replaced : T.denied), true); leaving = true; }
    };
    ws.onclose = function () {
      dropAll(); joined = false; me = null;
      if (leaving) return;
      status(T.reconnecting, true);
      setTimeout(function () { if (!leaving) connect(); }, 3000);
    };
  }

  $("join").addEventListener("click", function () {
    $("join").disabled = true;
    status(T.connecting);
    leaving = false;
    navigator.mediaDevices.getUserMedia(constraints()).then(function (s) {
      useStream(s);
      return listMics(s.getAudioTracks()[0].getSettings().deviceId);
    }).then(connect).catch(function () { status(T.nomic, true); $("join").disabled = false; });
  });

  $("mute").addEventListener("click", function () {
    muted = !muted;
    if (stream) stream.getAudioTracks().forEach(function (t) { t.enabled = !muted; });
    $("mute").textContent = muted ? T.unmute : T.mute;
    $("mute").className = muted ? "on" : "";
    send({ type: "mute", muted: muted });
    render();
  });

  function leave() {
    leaving = true;
    if (ws) ws.close();
    dropAll();
    if (stopMeter) stopMeter();
    if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
    stream = null; joined = false;
    $("level").style.width = "0";
    $("join").disabled = false; $("mute").disabled = true; $("leave").disabled = true;
    status(T.left);
    render();
  }
  $("leave").addEventListener("click", leave);
  window.addEventListener("pagehide", function () { leaving = true; if (ws) ws.close(); });
})();
`;
