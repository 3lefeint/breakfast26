<script>
  // Settings → Audio & Voice → Scenes: what happens at a special moment of a game, drawn as a flow. A trigger
  // node names a moment (a turn scored, a player eliminated, ...), condition nodes let the flow go on or stop it,
  // action nodes play a sound of the library, show an effect on the TV view or wait. Select a node and add the
  // next one: it is connected to the selected node. Drag from the dot below a node to another node to
  // connect them. A scene is saved with its Save button and works at once, without a restart.
  import { onMount, tick, untrack } from 'svelte';
  import { t } from '../../lib/i18n.js';
  import { confirmDialog } from '../../lib/confirm.js';
  import { apiJson } from '../../lib/api.js';
  import { listenForTest, listenerSound } from '../../lib/testListener.js';
  import Toggle from '../../lib/components/Toggle.svelte';
  import InfoTip from '../../lib/components/InfoTip.svelte';
  import SceneOverlay from '../../tv/views/SceneOverlay.svelte';

  const W = 250;
  const H = 62;
  const GAP_X = 40;
  const GAP_Y = 48;
  const ROW = 26;                    // a row of a switch: one output
  const MAX_SWITCH_OUTPUTS = 18;     // not counting "otherwise"
  // The height of a node: a switch grows downward with each output (and "otherwise"), inside the canvas.
  const hOf = (n) => (n.kind === 'switch' ? H + ((n.outputs?.length || 0) + 1) * ROW + 4 : H);
  const EVENT_LABEL = {
    'x01.dart': t('Dart thrown'), 'x01.match_start': t('Match starts'), 'x01.leg_start': t('Leg starts'), 'x01.turn_start': t('Turn starts'), 'x01.turn_scored': t('Turn scored'),
    'x01.bust': t('Bust'), 'x01.leg_won': t('Leg won'), 'x01.match_won': t('Match won'),
    'elim.match_start': t('Match starts'), 'elim.dart_missed': t('Missed dart'), 'elim.turn_counted': t('Score read late'),
    'elim.turn_start': t('Turn starts'), 'elim.passed': t('Turn passed'), 'elim.life_lost': t('Life lost'),
    'elim.eliminated': t('Player eliminated'), 'elim.match_won': t('Match won'),
    'achievement.earned': t('Achievement earned'),
  };
  const GAME_LABEL = { X01: 'X01', Elimination: t('Elimination'), Achievements: t('Achievements') };
  const FIELD_LABEL = {
    player: t('Player'),
    score: t('Score'), remaining: t('Remaining'), leg: t('Leg'), target: t('Target'), lives: t('Lives'),
    freipass: t('Free pass'), next: t('Score to pass'), margin: t('Over twice the target'),
    preview: t('Read after the 3rd dart'), close: t('Nearly enough'), last: t('Ends the match'),
    number: t('Field'), multiplier: t('Field type'),
    points: t('Points'), dart: t('Dart of the turn'), miss: t('Missed'), fun: t('Fun mode'),
    announce: t('Player calls on'), change: t('Player change calls on'), total: t('Turn total calls on'),
    checkout: t('Checkout'), id: t('Achievement'), tier: t('Tier'), difficulty: t('Difficulty'), secret: t('Secret'),
    first: t('Earned for the first time'),
  };
  const ANIMATION_LABEL = { confetti: t('Confetti'), flash: t('Flash'), banner: t('Banner') };
  const CHANNEL_LABEL = { voice: t('After the calls'), ambient: t('Next to the calls') };
  const FLAGS = ['freipass', 'preview', 'close', 'last', 'announce', 'change', 'total', 'miss', 'fun', 'secret', 'first'];    // facts that are 1 or 0
  const SCOPE_LABEL = { match: t('once per match'), leg: t('once per leg') };
  const ICON = { trigger: '⚡', condition: '◆', action: '♪' };

  let data = $state(null);
  let error = $state('');
  let message = $state('');
  let draft = $state(null);          // the scene being edited: { id, name, enabled, graph }, id null while unsaved
  let dirty = $state(false);
  let selNode = $state(null);
  let selEdge = $state(null);        // 'from>to'
  let link = $state(null);           // a connection being dragged: { from, x, y }
  let svgEl = $state();
  let drag = null;
  let playing = null;
  let focus = $state(false);         // the editor fills the whole window
  let view = $state({ x: 40, y: 40, k: 1 });    // the part of the canvas on the screen: offset and zoom
  let failed = $state([]);           // the nodes that could not run in the last test
  let picked = $state([]);           // the ids of several selected nodes (one selected node is `selNode`)
  let pan = null;                    // the view being moved: { x, y, vx, vy }
  let marquee = $state(null);        // a selection frame being drawn, in canvas coordinates: { x0, y0, x1, y1 }

  async function load(keep = true) {
    try {
      const body = await apiJson('GET', '/api/scenes');
      data = body;
      error = '';
      if (draft?.id != null && keep) {
        if (!dirty) {
          const fresh = body.scenes.find((s) => s.id === draft.id);
          if (fresh) pick(fresh); else draft = null;
        }
      } else if (!draft && body.scenes.length) {
        pick(body.scenes[0]);
      }
    } catch (e) {
      error = t('Could not load the scenes.');
    }
  }
  onMount(() => load());

  // The nodes in rows by depth, one column per end of the flow. A flow that was drawn from left to right is laid out so
  // when it is opened, the nodes stay where they are otherwise.
  function arrange(graph) {
    const byId = Object.fromEntries(graph.nodes.map((n) => [n.id, n]));
    // The children of a node in the order of its outputs: yes before no, the outputs of a switch top to bottom.
    const rank = (e) => {
      const from = byId[e.from];
      if (from?.kind === 'switch') {
        const i = from.outputs.findIndex((o) => o.id === e.match);
        return i < 0 ? from.outputs.length : i;
      }
      return e.branch === 'no' ? 1 : 0;
    };
    const kids = {};
    for (const e of [...graph.edges].sort((a, b) => rank(a) - rank(b))) (kids[e.from] ||= []).push(e.to);
    const done = new Set();
    let column = 0;
    function place(id, y) {
      const n = byId[id];
      if (!n || done.has(id)) return null;
      done.add(id);
      n.y = y;
      const xs = (kids[id] || []).map((c) => place(c, y + hOf(n) + GAP_Y)).filter((x) => x != null);
      n.x = xs.length ? Math.round(xs.reduce((a, b) => a + b, 0) / xs.length) : 40 + column++ * (W + GAP_X);
      return n.x;
    }
    const starts = graph.nodes.filter((n) => n.type === 'trigger').map((n) => n.id);
    for (const id of [...starts, ...graph.nodes.map((n) => n.id)]) place(id, 40);
  }

  const flowsDown = (graph) => graph.edges.every((e) => {
    const a = graph.nodes.find((n) => n.id === e.from);
    const b = graph.nodes.find((n) => n.id === e.to);
    return !a || !b || b.y >= a.y + hOf(a);
  });

  function tidy() {
    arrange(draft.graph);
    dirty = true;
    fitSoon();
  }

  function pick(scene) {
    resetHistory();
    failed = [];
    draft = JSON.parse(JSON.stringify(scene));
    if (!flowsDown(draft.graph)) arrange(draft.graph);
    dirty = false;
    selNode = null;
    selEdge = null;
    picked = [];
    fitSoon();
  }

  async function open(scene) {
    if (draft && scene.id === draft.id) return;
    if (dirty && !await confirmDialog(t('Discard the unsaved changes of this scene?'))) return;
    pick(scene);
  }

  async function create() {
    if (dirty && !await confirmDialog(t('Discard the unsaved changes of this scene?'))) return;
    resetHistory();
    draft = { id: null, name: t('New scene'), enabled: true, graph: { nodes: [], edges: [] } };
    dirty = true;
    selNode = null;
    selEdge = null;
    picked = [];
    fitSoon();
  }

  const touch = () => { dirty = true; };

  // ── undo and redo of the flow (Ctrl+Z, Ctrl+Y) ─────────────────────────────

  const HISTORY_MAX = 100;
  let past = [];                     // earlier states of the graph, as JSON, the newest last
  let future = [];
  let lastSnap = null;               // the state the editor is in now
  let burstBase = null;              // the state before a burst of changes (a drag, typing) that is still going on
  let burstTimer = null;
  let applying = false;

  function resetHistory() {
    clearTimeout(burstTimer);
    past = []; future = []; lastSnap = null; burstBase = null;
  }
  function closeBurst() {
    clearTimeout(burstTimer);
    if (burstBase !== null) {
      past.push(burstBase);
      if (past.length > HISTORY_MAX) past.shift();
      burstBase = null;
    }
  }
  $effect(() => {
    if (!draft) return;
    const snap = JSON.stringify(draft.graph);
    untrack(() => {
      if (lastSnap === null || applying) { lastSnap = snap; applying = false; return; }
      if (snap === lastSnap) return;
      if (burstBase === null) burstBase = lastSnap;
      lastSnap = snap;
      future = [];
      clearTimeout(burstTimer);
      burstTimer = setTimeout(closeBurst, 500);
    });
  });
  function goTo(snap) {
    applying = true;
    draft.graph = JSON.parse(snap);
    dirty = true;
    const ids = new Set(draft.graph.nodes.map((n) => n.id));
    if (selNode && !ids.has(selNode)) selNode = null;
    picked = picked.filter((id) => ids.has(id));
    if (selEdge && !draft.graph.edges.some((e) => `${e.from}>${e.to}` === selEdge)) selEdge = null;
  }
  function undo() {
    closeBurst();
    if (!past.length) return;
    future.push(lastSnap);
    goTo(past.pop());
  }
  function redo() {
    if (!future.length) return;
    closeBurst();
    past.push(lastSnap);
    goTo(future.pop());
  }

  let nodes = $derived(draft?.graph.nodes || []);
  let edges = $derived(draft?.graph.edges || []);
  let node = $derived(nodes.find((n) => n.id === selNode) || null);
  let hasTrigger = $derived(nodes.some((n) => n.type === 'trigger'));
  let events = $derived(data?.events || {});
  let library = $derived(data?.sounds || []);
  let achievements = $derived(data?.achievements || []);
  const achievementName = (id) => achievements.find((a) => a.id === id)?.name || id;

  // The facts a condition can look at: those of the events the scene has a trigger for.
  let facts = $derived.by(() => {
    const names = new Set();
    for (const n of nodes) if (n.type === 'trigger') Object.keys(events[n.event]?.fields || {}).forEach((f) => names.add(f));
    names.add('fun');
    return names;
  });
  let fields = $derived([...facts, ...(node?.kind === 'compare' && !facts.has(node.field) ? [node.field] : [])]);
  const isFlag = (f) => FLAGS.includes(f);
  const FIELD_DEFAULT = { score: 100, points: 60, remaining: 100, lives: 1, number: 20, multiplier: 3, dart: 1, checkout: 1, leg: 1, target: 60, next: 61 };
  // What a fact means and which values it takes, shown beside the condition (not in the name of the node).
  const FIELD_NOTE = {
    score: t('0 to 180'), points: t('0 to 60'), number: t('1 to 20, 25 is the bull (25 with field type 2 is the bullseye)'), dart: t('1 to 3'),
    multiplier: t('0 miss, 1 single, 2 double, 3 triple'), checkout: t('1 call, 2 bogey number, 3 call limit reached'),
    close: t('1 to 10 short'), difficulty: t('1 easy, 2 medium, 3 hard, 4 very hard, 5 extreme, 0 for endurance and secret ones'),
    tier: t('1 for an achievement without tiers'),
  };

  // What a condition on a fact starts with: a switch asks yes or no, a number a typical value.
  function compareFor(field) {
    return isFlag(field) ? { field, op: '==', value: 1 } : { field, op: '>=', value: FIELD_DEFAULT[field] ?? 0 };
  }
  function setField(field) {
    Object.assign(node, compareFor(field));
    touch();
  }

  function freeId() {
    let i = nodes.length + 1;
    while (nodes.some((n) => n.id === 'n' + i)) i++;
    return 'n' + i;
  }

  const DEFAULTS = {
    switch: { type: 'condition', kind: 'switch', field: 'player', mode: 'values', outputs: [{ id: 'o1', values: [] }, { id: 'o2', values: [] }] },
    compare: { type: 'condition', kind: 'compare', field: 'score', op: '>=', value: 100 },
    chance: { type: 'condition', kind: 'chance', percent: 10 },
    player: { type: 'condition', kind: 'player', names: [] },
    once: { type: 'condition', kind: 'once', scope: 'match', per_player: false },
    pick: { type: 'condition', kind: 'pick' },
    achievement: { type: 'condition', kind: 'achievement', achievement: '', tier: 1 },
    sound: { type: 'action', kind: 'sound', files: [{ file: '', weight: 1 }], volume: 1, replace: false, channel: 'ambient' },
    overlay: { type: 'action', kind: 'overlay', animation: 'confetti', text: '', seconds: 4 },
    delay: { type: 'action', kind: 'delay', seconds: 1 },
    call: { type: 'action', kind: 'call', key: '', channel: 'voice' },
  };

  function addNode(spec) {
    const from = nodes.find((n) => n.id === selNode);
    const id = freeId();
    if (spec.kind === 'compare') {
      const first = facts.has('score') ? 'score' : ([...facts].find((f) => f !== 'fun') || 'fun');
      spec = { ...spec, ...compareFor(first) };
    }
    let x = nodes.length ? Math.max(...nodes.map((n) => n.x)) + W + GAP_X : 40;
    let y = 40;
    if (from) {
      x = from.x + edges.filter((e) => e.from === from.id).length * (W + GAP_X);
      y = from.y + hOf(from) + GAP_Y;
    }
    draft.graph.nodes.push({ id, x, y, ...JSON.parse(JSON.stringify(spec)) });
    if (from) draft.graph.edges.push({ from: from.id, to: id });
    selNode = id;
    selEdge = null;
    picked = [];
    dirty = true;
  }

  function addTrigger(event) {
    if (event) addNode({ type: 'trigger', event });
  }

  function removeNodes(ids) {
    draft.graph.nodes = draft.graph.nodes.filter((n) => !ids.includes(n.id));
    draft.graph.edges = draft.graph.edges.filter((e) => !ids.includes(e.from) && !ids.includes(e.to));
    selNode = null;
    picked = [];
    dirty = true;
  }
  const removeNode = (id) => removeNodes([id]);

  function removeEdge(key) {
    draft.graph.edges = draft.graph.edges.filter((e) => `${e.from}>${e.to}` !== key);
    selEdge = null;
    dirty = true;
  }

  function onKey(e) {
    if (e.key === 'Escape' && focus) { focus = false; return; }
    if ((e.ctrlKey || e.metaKey) && draft && !/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement?.tagName)) {
      const key = e.key.toLowerCase();
      if (key === 'z' && !e.shiftKey) { e.preventDefault(); undo(); return; }
      if (key === 'y' || (key === 'z' && e.shiftKey)) { e.preventDefault(); redo(); return; }
    }
    if (e.key !== 'Delete' || !draft || /^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement?.tagName)) return;
    if (selEdge) removeEdge(selEdge);
    else if (picked.length > 1) removeNodes(picked);
    else if (selNode) removeNode(selNode);
  }

  // ── the canvas ──────────────────────────────────────────────────────────────

  // A point of the screen as a point of the canvas, whatever the zoom and the offset.
  const point = (e) => {
    const box = svgEl.getBoundingClientRect();
    return { x: (e.clientX - box.left - view.x) / view.k, y: (e.clientY - box.top - view.y) / view.k };
  };

  // Brings the whole flow into the window (never larger than its real size).
  function fit() {
    if (!svgEl) return;
    const box = svgEl.getBoundingClientRect();
    if (!nodes.length || !box.width) { view = { x: 40, y: 40, k: 1 }; return; }
    const x0 = Math.min(...nodes.map((n) => n.x)), x1 = Math.max(...nodes.map((n) => n.x + W));
    const y0 = Math.min(...nodes.map((n) => n.y)), y1 = Math.max(...nodes.map((n) => n.y + hOf(n) + 30));
    const k = Math.max(0.25, Math.min(1, (box.width - 80) / (x1 - x0), (box.height - 80) / (y1 - y0)));
    view = { k, x: (box.width - (x1 - x0) * k) / 2 - x0 * k, y: 40 - y0 * k };
  }
  const fitSoon = () => tick().then(fit);

  // Zoom around a point of the screen, so the spot under the pointer stays where it is.
  function zoomAt(factor, mx, my) {
    const k = Math.min(2.5, Math.max(0.25, view.k * factor));
    const wx = (mx - view.x) / view.k, wy = (my - view.y) / view.k;
    view = { k, x: mx - wx * k, y: my - wy * k };
  }
  function zoomCentre(factor) {
    const box = svgEl.getBoundingClientRect();
    zoomAt(factor, box.width / 2, box.height / 2);
  }

  // Ctrl + wheel (or a pinch) zooms; in the full window the wheel alone moves the view.
  $effect(() => {
    const el = svgEl;
    if (!el) return;
    const onWheel = (e) => {
      const box = el.getBoundingClientRect();
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX - box.left, e.clientY - box.top);
      } else if (focus) {
        e.preventDefault();
        view = { ...view, x: view.x - e.deltaX, y: view.y - e.deltaY };
      }
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  });

  async function toggleFocus() {
    focus = !focus;
    await tick();
    fit();
  }

  // The background: a drag moves the view, Shift + drag draws a frame that selects the nodes inside it.
  function startBackground(e) {
    selNode = null;
    selEdge = null;
    if (e.shiftKey || e.ctrlKey || e.metaKey) {
      const p = point(e);
      marquee = { x0: p.x, y0: p.y, x1: p.x, y1: p.y };
    } else {
      picked = [];
      pan = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
    }
    svgEl.setPointerCapture(e.pointerId);
  }

  const isPicked = (id) => selNode === id || picked.includes(id);

  function startDrag(e, n) {
    if (e.button === 1) { e.preventDefault(); return; }    // the middle button removes the node, see onauxclick
    if (e.button !== 0) return;
    const p = point(e);
    selEdge = null;
    if (e.shiftKey || e.ctrlKey || e.metaKey) {         // add the node to the selection or take it out
      const now = picked.length ? picked : (selNode ? [selNode] : []);
      const next = now.includes(n.id) ? now.filter((id) => id !== n.id) : [...now, n.id];
      picked = next.length > 1 ? next : [];
      selNode = next.length === 1 ? next[0] : null;
      return;
    }
    if (picked.length > 1 && picked.includes(n.id)) {
      selNode = null;
    } else {
      picked = [];
      selNode = n.id;
    }
    const moving = picked.length > 1 ? picked : [n.id];
    drag = { px: p.x, py: p.y, starts: moving.map((id) => { const m = nodes.find((x) => x.id === id); return { m, x: m.x, y: m.y }; }) };
    svgEl.setPointerCapture(e.pointerId);
  }

  // A condition leads on from two outputs, yes (left) and no (right); a random pick and every other node from one.
  const twoWay = (n) => n.type === 'condition' && n.kind !== 'pick' && n.kind !== 'switch';

  // Where a connection leaves a node: *key* is yes or no for a condition, the id of an output (or "else") for a switch.
  function outPort(n, key) {
    if (n.kind === 'switch') {
      const i = n.outputs.findIndex((o) => o.id === key);
      return { x: n.x + W, y: n.y + H + (i < 0 ? n.outputs.length : i) * ROW + ROW / 2, side: true };
    }
    return { x: n.x + (twoWay(n) ? (key === 'no' ? W * 0.7 : W * 0.3) : W / 2), y: n.y + H, side: false };
  }
  const keyOf = (n, edge) => (n.kind === 'switch' ? edge.match : edge.branch);

  function startLink(e, n, key) {
    e.stopPropagation();
    selNode = n.id;
    selEdge = null;
    link = { from: n.id, key, ...point(e) };
    svgEl.setPointerCapture(e.pointerId);
  }

  function onMove(e) {
    if (pan) { view = { ...view, x: pan.vx + e.clientX - pan.x, y: pan.vy + e.clientY - pan.y }; return; }
    if (marquee) { const q = point(e); marquee.x1 = q.x; marquee.y1 = q.y; return; }
    if (!drag && !link) return;
    const p = point(e);
    if (drag) {
      for (const s of drag.starts) {
        const x = Math.max(-4000, Math.min(4000, Math.round(s.x + p.x - drag.px)));
        const y = Math.max(-4000, Math.min(4000, Math.round(s.y + p.y - drag.py)));
        if (s.m.x !== x || s.m.y !== y) { s.m.x = x; s.m.y = y; dirty = true; }
      }
    } else {
      link.x = p.x;
      link.y = p.y;
    }
  }

  function onUp(e) {
    if (link) {
      const p = point(e);
      const target = nodes.find((n) => p.x >= n.x && p.x <= n.x + W && p.y >= n.y && p.y <= n.y + hOf(n));
      if (target && target.id !== link.from && target.type !== 'trigger'
          && !edges.some((x) => x.from === link.from && x.to === target.id)) {
        const from = nodes.find((n) => n.id === link.from);
        if (from?.kind === 'switch') draft.graph.edges.push({ from: link.from, to: target.id, match: link.key });
        else draft.graph.edges.push(link.key === 'no' ? { from: link.from, to: target.id, branch: 'no' } : { from: link.from, to: target.id });
        dirty = true;
      }
    }
    if (marquee) {
      const x0 = Math.min(marquee.x0, marquee.x1), x1 = Math.max(marquee.x0, marquee.x1);
      const y0 = Math.min(marquee.y0, marquee.y1), y1 = Math.max(marquee.y0, marquee.y1);
      const inside = nodes.filter((n) => n.x < x1 && n.x + W > x0 && n.y < y1 && n.y + hOf(n) > y0).map((n) => n.id);
      picked = inside.length > 1 ? inside : [];
      selNode = inside.length === 1 ? inside[0] : null;
    }
    marquee = null;
    pan = null;
    link = null;
    drag = null;
  }

  // A connection leaves a node downward, that of a switch to the right first.
  const curve = (x1, y1, x2, y2, side = false) => {
    const dy = Math.max(30, Math.abs(y2 - y1) / 2);
    return side ? `M${x1},${y1} C${x1 + 60},${y1} ${x2},${y2 - dy} ${x2},${y2}` : `M${x1},${y1} C${x1},${y1 + dy} ${x2},${y2 - dy} ${x2},${y2}`;
  };

  function edgePath(edge) {
    const a = nodes.find((n) => n.id === edge.from);
    const b = nodes.find((n) => n.id === edge.to);
    if (!a || !b) return '';
    const from = outPort(a, keyOf(a, edge));
    return curve(from.x, from.y, b.x + W / 2, b.y, from.side);
  }

  function edgeMid(edge) {
    const a = nodes.find((n) => n.id === edge.from);
    const b = nodes.find((n) => n.id === edge.to);
    if (!a || !b) return { x: 0, y: 0 };
    const from = outPort(a, keyOf(a, edge));
    return { x: (from.x + b.x + W / 2) / 2, y: (from.y + b.y) / 2 };
  }

  function linkPath() {
    const a = nodes.find((n) => n.id === link.from);
    if (!a) return '';
    const from = outPort(a, link.key);
    return curve(from.x, from.y, link.x, link.y, from.side);
  }

  // A standard scene is named after the moment it belongs to, in the language of the interface.
  function momentOf(scene) {
    const trigger = scene.graph.nodes.find((n) => n.type === 'trigger');
    return trigger ? EVENT_LABEL[trigger.event] || trigger.event : scene.name;
  }

  function titleOf(scene) {
    if (!scene.default) return scene.name;
    const trigger = scene.graph.nodes.find((n) => n.type === 'trigger');
    const game = events[trigger?.event]?.game;
    return `${GAME_LABEL[game] || game}: ${momentOf(scene)}`;
  }

  // The scenes by the game they belong to: those that come with the program first, then the scenes of the user.
  function gameOf(scene) {
    if (scene.game) return scene.game;
    const trigger = scene.graph.nodes.find((n) => n.type === 'trigger');
    return events[trigger?.event]?.game || '';
  }

  let sections = $derived.by(() => {
    const groups = {};
    for (const scene of data?.scenes || []) (groups[gameOf(scene)] ||= []).push(scene);
    for (const list of Object.values(groups)) list.sort((a, b) => Number(b.default) - Number(a.default));
    const order = Object.keys(events).map((id) => events[id].game);
    return Object.entries(groups).sort((a, b) => {
      const ia = order.indexOf(a[0]);
      const ib = order.indexOf(b[0]);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    });
  });

  // The text of a node is cut by its width on the screen, so it never runs over the edge of the node.
  let measure = null;
  function fitText(text, maxPx) {
    measure ||= document.createElement('canvas').getContext('2d');
    measure.font = `600 14px ${svgEl ? getComputedStyle(svgEl).fontFamily : 'sans-serif'}`;
    if (measure.measureText(text).width <= maxPx) return text;
    let lo = 0, hi = text.length;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (measure.measureText(text.slice(0, mid) + '…').width <= maxPx) lo = mid; else hi = mid - 1;
    }
    return text.slice(0, lo) + '…';
  }
  const cut = (text, width = W - 32) => fitText(text, width);

  function describe(n) {
    if (n.type === 'trigger') {
      const game = events[n.event]?.game;
      return [t('When'), cut(`${GAME_LABEL[game] || game} · ${EVENT_LABEL[n.event] || n.event}`)];
    }
    const missing = n.kind === 'compare' && hasTrigger && !facts.has(n.field) ? ' ⚠' : '';
    if (n.kind === 'compare' && FLAGS.includes(n.field) && n.op === '==') {
      return [t('If'), cut(`${FIELD_LABEL[n.field]}: ${n.value ? t('yes') : t('no')}${missing}`)];
    }
    if (n.kind === 'compare') return [t('If'), cut(`${FIELD_LABEL[n.field] || n.field} ${n.op} ${n.value}${missing}`)];
    if (n.kind === 'chance') return [t('If'), cut(t('{percent} % chance', { percent: n.percent }))];
    if (n.kind === 'player') return [t('If'), cut(n.names.length ? t('player is {names}', { names: n.names.join(', ') }) : t('any player'))];
    if (n.kind === 'once') return [t('If'), cut(SCOPE_LABEL[n.scope] + (n.per_player ? ` · ${t('per player')}` : ''))];
    if (n.kind === 'achievement') return [t('If'), cut(n.achievement ? t('has {name}', { name: achievementName(n.achievement) }) : t('has an achievement'))];
    if (n.kind === 'pick') return [t('Random'), cut(t('one of the next steps'))];
    if (n.kind === 'switch') return [t('Switch'), cut(FIELD_LABEL[n.field] || n.field)];
    if (n.kind === 'call') return [t('Play call'), cut(n.key || t('(no call)'))];
    if (n.kind === 'sound') {
      const named = n.files.filter((e) => e.file);
      const label = named.length > 1 ? t('{n} sounds', { n: named.length }) : (named[0]?.file || t('(no file)'));
      return [t('Play sound'), cut(label + (n.replace ? ' ⇄' : ''))];
    }
    if (n.kind === 'overlay') return [t('Show'), cut(ANIMATION_LABEL[n.animation] + (n.text ? ` · ${n.text}` : ''))];
    return [t('Wait'), t('{seconds} s', { seconds: n.seconds })];
  }

  const MAX_SOUND_FILES = 20;

  function addSoundFile(node) {
    node.files.push({ file: '', weight: 1 });
    touch();
  }

  function removeSoundFile(node, index) {
    node.files.splice(index, 1);
    touch();
  }

  // The share of a file in percent; a file that is not in the library is left out when it plays, the others share its weight.
  function shareOf(node, entry) {
    const there = (e) => e.file && library.some((f) => f.name === e.file);
    if (!there(entry)) return '';
    const total = node.files.filter(there).reduce((sum, e) => sum + (Number(e.weight) || 0), 0);
    return total ? `${Math.round((Number(entry.weight) || 0) / total * 100)} %` : '';
  }

  // ── the voice slot ─────────────────────────────────────────────────────────

  // Per moment the first scene of the user (in list order) that plays on the voice channel takes the voice. The server works
  // out which earlier scenes can take it before the scene being edited, with the unsaved changes.
  let slotNotes = $state([]);
  let slotTimer = null;
  $effect(() => {
    if (!draft || draft.default) { slotNotes = []; return; }
    const body = { id: draft.id, graph: JSON.parse(JSON.stringify(draft.graph)) };
    void data;                          // the saved scenes and their order
    clearTimeout(slotTimer);
    slotTimer = setTimeout(async () => {
      try {
        slotNotes = (await apiJson('POST', '/api/scenes/voice-check', body)).overridden_by || [];
      } catch (e) {
        slotNotes = [];
      }
    }, 400);
  });
  const momentName = (event) => `${GAME_LABEL[events[event]?.game] || events[event]?.game} · ${EVENT_LABEL[event] || event}`;

  const mineOf = (list) => list.filter((x) => !x.default);
  const canMove = (list, scene, delta) => {
    const i = mineOf(list).findIndex((x) => x.id === scene.id);
    return i + delta >= 0 && i + delta < mineOf(list).length;
  };
  async function move(list, scene, delta) {
    if (!canMove(list, scene, delta)) return;
    const mine = mineOf(list);
    const other = mine[mine.findIndex((x) => x.id === scene.id) + delta];
    const ids = data.scenes.filter((x) => !x.default).map((x) => x.id);
    const a = ids.indexOf(scene.id), b = ids.indexOf(other.id);
    [ids[a], ids[b]] = [ids[b], ids[a]];
    const res = await apiJson('POST', '/api/scenes/order', { ids });
    if (res.error) { message = t(res.error); return; }
    await load();
  }

  // ── the switch node ─────────────────────────────────────────────────────────

  const TEXT_FACTS = ['player', 'id'];       // facts that are names, read as values; the others are numbers, read as bands
  let switchFields = $derived([...new Set(['player', ...facts, ...(node?.kind === 'switch' ? [node.field] : [])])]);

  // The label of an output: its values or its upper limit; the last row takes what no output did.
  function outputLabel(n, o) {
    if (n.mode === 'bands') return `≤ ${o.limit}`;
    return o.values.length ? o.values.join(', ') : t('(no value)');
  }
  function switchRows(n) {
    return [...n.outputs.map((o) => ({ id: o.id, label: outputLabel(n, o) })), { id: 'else', label: t('otherwise') }];
  }

  function setSwitchField(n, field) {
    n.field = field;
    setSwitchMode(n, TEXT_FACTS.includes(field) ? 'values' : 'bands');
  }

  // A change of the mode keeps the outputs (and what hangs on them) and gives them fresh values.
  function setSwitchMode(n, mode) {
    if (n.mode !== mode) {
      n.outputs = n.outputs.map((o, i) => (mode === 'bands' ? { id: o.id, limit: (i + 1) * 10 } : { id: o.id, values: [] }));
      n.mode = mode;
    }
    touch();
  }

  function addOutput(n) {
    if (n.outputs.length >= MAX_SWITCH_OUTPUTS) return;
    let i = n.outputs.length + 1;
    while (n.outputs.some((o) => o.id === 'o' + i)) i++;
    const last = n.outputs[n.outputs.length - 1];
    n.outputs.push(n.mode === 'bands' ? { id: 'o' + i, limit: last ? last.limit + 10 : 10 } : { id: 'o' + i, values: [] });
    touch();
  }

  function removeOutput(n, index) {
    const [gone] = n.outputs.splice(index, 1);
    draft.graph.edges = draft.graph.edges.filter((e) => !(e.from === n.id && e.match === gone.id));
    selEdge = null;
    touch();
  }

  // Values are typed with commas. A value sits on one output only: the output it was typed into keeps it.
  function setValues(n, output, text) {
    output.values = [...new Set(text.split(',').map((v) => v.trim()).filter(Boolean))];
    const mine = new Set(output.values.map((v) => v.toLowerCase()));
    for (const o of n.outputs) if (o !== output) o.values = o.values.filter((v) => !mine.has(v.toLowerCase()));
    touch();
  }

  // A band starts where the one before it ends, so the limits are kept in ascending order.
  function sortBands(n) {
    for (const o of n.outputs) o.limit = Number(o.limit) || 0;
    n.outputs.sort((a, b) => a.limit - b.limit);
    touch();
  }

  // ── saving, testing ────────────────────────────────────────────────────────

  async function save() {
    message = '';
    const body = { name: draft.name, enabled: draft.enabled, graph: draft.graph };
    const res = draft.id == null ? await apiJson('POST', '/api/scenes', body) : await apiJson('PUT', `/api/scenes/${draft.id}`, body);
    if (res.error) { message = t(res.error); return false; }
    draft.id = res.id;
    dirty = false;
    await load();
    return true;
  }

  const WHY = {
    no_audio: t('no audio output is set up'), no_file: t('no file chosen'), file_missing: t('the file is not in the library'),
    no_key: t('no call chosen'), no_sound: t('the voice pack has no sound for it'), ambient_muted: t('the ambient volume is 0'),
    no_display: t('no view is connected to show it'), voice_slot_taken: t('an earlier scene already plays the voice at this moment'),
    no_output: t('nothing is connected to the output it took'),
    not_a_number: t('the value is not a number'),
  };
  function whyText(why = '') {
    const [code, rest = ''] = why.split(':');
    if (code === 'missing_fact') return t('no value for {facts}', { facts: rest.split(',').map((f) => FIELD_LABEL[f] || f).join(', ') });
    return WHY[code] || t('it did not run');
  }

  async function test() {
    failed = [];
    const listening = listenForTest();    // first, while the click still counts for the browser
    if (dirty && !await save()) return;
    await listening;
    // The sound plays where an audio page is open already; this page then only shows the effects.
    const others = ((await apiJson('GET', '/api/scenes/audio-clients')).count || 0) > 1;
    listenerSound(!others);
    const res = await apiJson('POST', `/api/scenes/${draft.id}/test`);
    if (res.error) { message = t(res.error); return; }
    const skipped = res.trace.filter((s) => s.result === 'skipped');
    failed = skipped.map((s) => s.node);
    if (skipped.length) {
      const list = skipped.map((s) => {
        const n = nodes.find((x) => x.id === s.node);
        return n ? `${describe(n).join(' ')}: ${whyText(s.why)}` : whyText(s.why);
      }).join('; ');
      message = skipped.length === 1 ? t('1 step could not run: {list}', { list }) : t('{n} steps could not run: {list}', { n: skipped.length, list });
      return;
    }
    message = res.trace.length ? t('Played the scene with sample values.') : t('Nothing happened: add an action after a trigger.');
    const played = res.trace.filter((s) => s.file).map((s) => s.file);
    if (played.length) message += ' ' + t('Sound: {files}.', { files: played.join(', ') });
    const notes = res.trace.filter((s) => s.result !== 'skipped' && s.why).map((s) => {
      const n = nodes.find((x) => x.id === s.node);
      return `${n ? describe(n).join(' ') : s.node}: ${whyText(s.why)}`;
    });
    if (notes.length) message += ' ' + notes.join('; ') + '.';
    const left = res.trace.flatMap((s) => s.missing || []);
    if (left.length) message += ' ' + t('Not in the library, left out: {files}.', { files: left.join(', ') });
    if (res.trace.length && others) message += ' ' + t('The sound comes from the connected audio page.');
  }

  async function remove() {
    if (draft.default) {
      if (!await confirmDialog(t('Go back to the original of {name}? Your changes to it are lost.', { name: titleOf(draft) }))) return;
      const res = await apiJson('DELETE', `/api/scenes/${draft.id}`);
      if (res.error) { message = t(res.error); return; }
      dirty = false;
      await load();
      return;
    }
    if (!await confirmDialog(t('Delete the scene {name}?', { name: draft.name }))) return;
    if (draft.id != null) {
      const res = await apiJson('DELETE', `/api/scenes/${draft.id}`);
      if (res.error) { message = t(res.error); return; }
    }
    draft = null;
    dirty = false;
    await load(false);
  }

  async function toggleScene(scene) {
    const res = await apiJson('PUT', `/api/scenes/${scene.id}`, { name: scene.name, enabled: !scene.enabled, graph: scene.graph });
    if (res.error) { message = t(res.error); return; }
    if (draft?.id === scene.id) draft.enabled = !scene.enabled;
    await load();
  }

  // ── the sound library ──────────────────────────────────────────────────────

  function preview(file) {
    if (!file) return;
    if (playing) playing.pause();
    playing = new Audio(`/api/sound/${encodeURIComponent(file)}`);
    playing.play().catch(() => { message = t('Could not play {file}.', { file }); });
  }

  const setNames = (value) => { node.names = value.split(',').map((x) => x.trim()).filter(Boolean); touch(); };
  const eventGroups = $derived.by(() => {
    const groups = {};
    for (const [id, ev] of Object.entries(events)) (groups[ev.game] ||= []).push(id);
    return Object.entries(groups);
  });
</script>

<svelte:window onkeydown={onKey} />

{#if error}
  <div class="empty">{error}</div>
{:else if !data}
  <div class="empty">{t('Loading…')}</div>
{:else if !data.available}
  <div class="empty">{t('Scenes are not available.')}</div>
{:else}
  <div class="intro">
    {t('A scene starts with a trigger, a moment of the game. Conditions let it go on or stop it, actions play a sound, show an effect on the TV view or wait. Select a node and add the next one: it is connected to the selected node. Drag from the dot below a node to another node to connect them.')}
  </div>
  {#if message && !draft}<div class="message">{message}</div>{/if}

  <div class="layout">
    <aside>
      <div class="box">
        <div class="box-head">
          <span class="box-title">{t('Scenes')}</span>
          <button type="button" class="act" onclick={create}>{t('+ New scene')}</button>
        </div>
        {#if draft && draft.id == null}
          <ul class="scene-list">
            <li class="current"><span class="scene-name">{draft.name}</span></li>
          </ul>
        {/if}
        {#each sections as [game, list], gi (game)}
          <div class="group" class:first={gi === 0}>{GAME_LABEL[game] || game}</div>
          <ul class="scene-list">
            {#each list as s, i (s.id)}
              {#if i > 0 && !s.default && list[i - 1].default}<li class="custom-line" aria-hidden="true"><span>{t('Custom')}</span></li>{/if}
              <li class:current={draft?.id === s.id}>
                <button type="button" class="scene-name" onclick={() => open(s)}>
                  {s.default ? momentOf(s) : s.name}{#if s.customized}<span class="edited"> · {t('edited')}</span>{/if}
                </button>
                {#if !s.default}
                  <button type="button" class="play" disabled={!canMove(list, s, -1)} title={t('Move up')} aria-label={t('Move {name} up', { name: s.name })}
                          onclick={() => move(list, s, -1)}>▲</button>
                  <button type="button" class="play" disabled={!canMove(list, s, 1)} title={t('Move down')} aria-label={t('Move {name} down', { name: s.name })}
                          onclick={() => move(list, s, 1)}>▼</button>
                {/if}
                <input type="checkbox" checked={s.enabled} title={t('On')} aria-label={t('{name} is on', { name: s.name })}
                       onchange={() => toggleScene(s)}>
              </li>
            {/each}
          </ul>
        {/each}
      </div>

      <div class="box">
        <div class="box-head"><span class="box-title">{t('Sound library')}</span></div>
        <div class="note">{t('Sounds are uploaded, cut and renamed in the Sounds tab.')}</div>
      </div>
    </aside>

    <section class="editor" class:focus>
      {#if !draft}
        <div class="empty">{t('Pick a scene or make a new one.')}</div>
      {:else}
        <SceneOverlay />        <!-- the effects of a test -->
        <div class="scene-head">
          <input class="scene-title" type="text" value={titleOf(draft)} maxlength="80" readonly={draft.default}
                 oninput={(e) => { draft.name = e.target.value; touch(); }} aria-label={t('Name of the scene')}>
          {#if draft.default}
            <InfoTip>{t('A standard scene makes the calls the game made on its own. What you change here replaces it, until you go back to the original.')}</InfoTip>
          {:else}
            <span class="slot-info" class:warn={slotNotes.some((n) => n.level === 'warning')}>
              {#if slotNotes.length}
                <InfoTip>
                  <p>{t('Per moment only one of your scenes plays a voice: the first one in the list that plays a sound or a call on the voice channel. The voice steps of the scenes after it are skipped; ambient sounds and effects always play.')}</p>
                  <ul>
                    {#each slotNotes as n}
                      <li>
                        {#if n.level === 'warning'}
                          <strong>{t('Always overridden')}</strong>: {t('"{name}" comes first at {moment} and always takes the voice. Move this scene above it or give the other one a condition.', { name: n.name, moment: momentName(n.event) })}
                        {:else}
                          {t('"{name}" comes first at {moment} and can take the voice before this scene.', { name: n.name, moment: momentName(n.event) })}
                        {/if}
                      </li>
                    {/each}
                  </ul>
                </InfoTip>
              {/if}
            </span>
          {/if}
          <Toggle bind:checked={draft.enabled} label={t('On')} wide onchange={touch} />
          <span class="spacer"></span>
          {#if dirty}<span class="dirty">{t('Unsaved changes')}</span>{/if}
          <button type="button" class="act primary" onclick={save} disabled={!dirty}>{t('Save')}</button>
          <button type="button" class="act" onclick={test}>{t('Test')}</button>
          {#if draft.default}
            <button type="button" class="act danger" onclick={remove} disabled={!draft.customized}>{t('Back to the original')}</button>
          {:else}
            <button type="button" class="act danger" onclick={remove}>{t('Delete')}</button>
          {/if}
        </div>

        <div class="palette">
          <select aria-label={t('Add a trigger')} onchange={(e) => { addTrigger(e.target.value); e.target.value = ''; }}>
            <option value="">{t('+ Trigger…')}</option>
            {#each eventGroups as [game, ids]}
              <optgroup label={GAME_LABEL[game] || game}>
                {#each ids as id}<option value={id}>{EVENT_LABEL[id] || id}</option>{/each}
              </optgroup>
            {/each}
          </select>
          <button type="button" class="act" onclick={() => addNode(DEFAULTS.compare)}>{t('+ Compare')}</button>
          <button type="button" class="act" onclick={() => addNode(DEFAULTS.chance)}>{t('+ Chance')}</button>
          <button type="button" class="act" onclick={() => addNode(DEFAULTS.player)}>{t('+ Player')}</button>
          <button type="button" class="act" onclick={() => addNode(DEFAULTS.once)}>{t('+ Once')}</button>
          <button type="button" class="act" onclick={() => addNode(DEFAULTS.achievement)}>{t('+ Achievement')}</button>
          <button type="button" class="act" onclick={() => addNode(DEFAULTS.pick)}>{t('+ Random')}</button>
          <button type="button" class="act" onclick={() => addNode(DEFAULTS.switch)}>{t('+ Switch')}</button>
          <button type="button" class="act" onclick={() => addNode(DEFAULTS.call)}>{t('+ Call')}</button>
          <button type="button" class="act" onclick={() => addNode(DEFAULTS.sound)}>{t('+ Sound')}</button>
          <button type="button" class="act" onclick={() => addNode(DEFAULTS.overlay)}>{t('+ Effect')}</button>
          <button type="button" class="act" onclick={() => addNode(DEFAULTS.delay)}>{t('+ Wait')}</button>
          <button type="button" class="act" onclick={tidy} disabled={!nodes.length}>{t('Tidy up')}</button>
        </div>

        <div class="work">
        <div class="canvas">
          {#if message}
            <button type="button" class="canvas-message" onclick={() => (message = '')} title={t('Click to close')}>{message}</button>
          {/if}
          {#if !hasTrigger}<div class="canvas-note">{t('Start with a trigger: without one the scene never runs.')}</div>{/if}
          <div class="zoom">
            <button type="button" class="act" onclick={() => zoomCentre(1 / 1.25)} aria-label={t('Zoom out')}>−</button>
            <span class="zoom-level">{Math.round(view.k * 100)} %</span>
            <button type="button" class="act" onclick={() => zoomCentre(1.25)} aria-label={t('Zoom in')}>+</button>
            <button type="button" class="act" onclick={fit}>{t('Fit')}</button>
            <button type="button" class="act icon" onclick={toggleFocus} title={focus ? t('Leave full window') : t('Full window')}
                    aria-label={focus ? t('Leave full window') : t('Full window')}>
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                {#if focus}<path d="M9 3v4a2 2 0 0 1-2 2H3M15 3v4a2 2 0 0 0 2 2h4M9 21v-4a2 2 0 0 0-2-2H3M15 21v-4a2 2 0 0 1 2-2h4"/>
                {:else}<path d="M3 9V5a2 2 0 0 1 2-2h4M15 3h4a2 2 0 0 1 2 2v4M21 15v4a2 2 0 0 1-2 2h-4M9 21H5a2 2 0 0 1-2-2v-4"/>{/if}
              </svg>
            </button>
          </div>
          <!-- svelte-ignore a11y_no_static_element_interactions -->
          <svg bind:this={svgEl} onpointermove={onMove} onpointerup={onUp}
               onpointercancel={onUp}>
            <rect class="bg" width="100%" height="100%" onpointerdown={startBackground} />
            <g transform="translate({view.x},{view.y}) scale({view.k})">
            {#each edges as edge (edge.from + '>' + edge.to)}
              {@const key = edge.from + '>' + edge.to}
              <path class="edge" class:sel={selEdge === key} d={edgePath(edge)} />
              <path class="edge-hit" d={edgePath(edge)} role="button" tabindex="-1" aria-label={t('Connection')}
                    onpointerdown={(e) => { e.stopPropagation(); if (e.button === 1) e.preventDefault(); selEdge = key; selNode = null; picked = []; }}
                    onauxclick={(e) => { if (e.button === 1) removeEdge(key); }}
                    ondblclick={() => removeEdge(key)} />
              {#if selEdge === key}
                {@const mid = edgeMid(edge)}
                <g class="edge-x" transform="translate({mid.x},{mid.y})" role="button" tabindex="-1" aria-label={t('Remove connection')}
                   onpointerdown={(e) => { e.stopPropagation(); removeEdge(key); }}>
                  <circle r="10" />
                  <path d="M-4,-4 L4,4 M4,-4 L-4,4" />
                </g>
              {/if}
            {/each}
            {#if link}<path class="edge ghost" d={linkPath()} />{/if}
            {#each nodes as n (n.id)}
              {@const [title, detail] = describe(n)}
              <g class="node {n.type}" class:sel={isPicked(n.id)} class:failed={failed.includes(n.id)} transform="translate({n.x},{n.y})"
                 role="button" tabindex="0" aria-label={`${title} ${detail}`}
                 onpointerdown={(e) => startDrag(e, n)}
                 onauxclick={(e) => { if (e.button === 1) removeNode(n.id); }}
                 onkeydown={(e) => { if (e.key === 'Enter') { selNode = n.id; selEdge = null; } }}>
                <rect width={W} height={hOf(n)} rx="10" />
                <text class="title" x="14" y="24">{ICON[n.type]} {title}</text>
                <text class="detail" x="14" y="46">{detail}</text>
                {#if n.type !== 'trigger'}<circle class="port" cx={W / 2} cy="0" r="6" />{/if}
                {#if n.kind === 'switch'}
                  {#each switchRows(n) as row, i (row.id)}
                    <line class="row-line" x1="0" x2={W} y1={H + i * ROW} y2={H + i * ROW} />
                    <text class="row-label" x="14" y={H + i * ROW + 18}>{cut(row.label, W - 60)}</text>
                    <circle class="port out" cx={W} cy={H + i * ROW + ROW / 2} r="8" role="button" tabindex="-1"
                            aria-label={t('Drag to connect from {output}', { output: row.label })} onpointerdown={(e) => startLink(e, n, row.id)} />
                  {/each}
                {:else if twoWay(n)}
                  <circle class="port out yes" cx={W * 0.3} cy={H} r="8" role="button" tabindex="-1"
                          aria-label={t('Drag to connect on yes')} onpointerdown={(e) => startLink(e, n, 'yes')} />
                  <circle class="port out no" cx={W * 0.7} cy={H} r="8" role="button" tabindex="-1"
                          aria-label={t('Drag to connect on no')} onpointerdown={(e) => startLink(e, n, 'no')} />
                  <text class="branch yes" x={W * 0.3 + 12} y={H + 16}>{t('yes')}</text>
                  <text class="branch no" x={W * 0.7 + 12} y={H + 16}>{t('no')}</text>
                {:else}
                  <circle class="port out" cx={W / 2} cy={H} r="8" role="button" tabindex="-1"
                          aria-label={t('Drag to connect')} onpointerdown={(e) => startLink(e, n)} />
                {/if}
              </g>
            {/each}
            {#if marquee}
              <rect class="marquee" x={Math.min(marquee.x0, marquee.x1)} y={Math.min(marquee.y0, marquee.y1)}
                    width={Math.abs(marquee.x1 - marquee.x0)} height={Math.abs(marquee.y1 - marquee.y0)} />
            {/if}
            </g>
          </svg>
        </div>
        <div class="canvas-hint">{t('Drag the background to move the view, Ctrl + wheel to zoom, Shift + drag to select several nodes and move them together.')}</div>

        {#if selEdge}
          {@const edge = edges.find((e) => `${e.from}>${e.to}` === selEdge)}
          {@const source = edge && nodes.find((n) => n.id === edge.from)}
          <div class="inspector">
            <span>{t('Connection')}</span>
            {#if source && twoWay(source)}
              <label>{t('Leaves the node on')}
                <select value={edge.branch === 'no' ? 'no' : 'yes'}
                        onchange={(e) => { if (e.target.value === 'no') edge.branch = 'no'; else delete edge.branch; touch(); }}>
                  <option value="yes">{t('yes')}</option>
                  <option value="no">{t('no')}</option>
                </select>
              </label>
            {:else if source?.kind === 'switch'}
              <label>{t('Leaves the node at')}
                <select value={edge.match} onchange={(e) => { edge.match = e.target.value; touch(); }}>
                  {#each switchRows(source) as row}<option value={row.id}>{row.label}</option>{/each}
                </select>
              </label>
            {:else if source?.kind === 'pick'}
              <label>{t('Weight')}
                <input type="number" min="1" max="100" step="any" value={edge.weight ?? 1}
                       oninput={(e) => { const w = Number(e.target.value) || 1; if (w === 1) delete edge.weight; else edge.weight = w; touch(); }}>
              </label>
              <span class="note">{t('A step with the weight 2 is picked twice as often as one with 1.')}</span>
            {/if}
            <button type="button" class="act danger" onclick={() => removeEdge(selEdge)}>{t('Remove connection')}</button>
          </div>
        {:else if node}
          <div class="inspector">
            <div class="insp-title">{ICON[node.type]} {describe(node)[0]}</div>
            {#if node.type === 'trigger'}
              <label>{t('Moment')}
                <select bind:value={node.event} onchange={touch}>
                  {#each eventGroups as [game, ids]}
                    <optgroup label={GAME_LABEL[game] || game}>
                      {#each ids as id}<option value={id}>{EVENT_LABEL[id] || id}</option>{/each}
                    </optgroup>
                  {/each}
                </select>
              </label>
            {:else if node.kind === 'compare'}
              <label>{t('Fact')}
                <select value={node.field} onchange={(e) => setField(e.target.value)}>
                  {#each fields as f}<option value={f}>{FIELD_LABEL[f] || f}{facts.has(f) ? '' : ` (${t('not given by the trigger')})`}</option>{/each}
                </select>
              </label>
              {#if isFlag(node.field)}
                <label>{t('Is')}
                  <select value={node.value ? '1' : '0'} onchange={(e) => { node.op = '=='; node.value = Number(e.target.value); touch(); }}>
                    <option value="1">{t('yes')}</option>
                    <option value="0">{t('no')}</option>
                  </select>
                </label>
              {:else}
                <label>{t('Is')}
                  <select bind:value={node.op} onchange={touch}>
                    {#each data.operators as op}<option value={op}>{op}</option>{/each}
                  </select>
                </label>
                <label>{t('Value')}<input type="number" bind:value={node.value} oninput={touch}></label>
              {/if}
              {#if FIELD_NOTE[node.field]}<span class="note">{FIELD_NOTE[node.field]}</span>{/if}
              {#if hasTrigger && !facts.has(node.field)}
                <span class="note warn">{t('The trigger of this scene gives no value for this fact, so the condition is never met.')}</span>
              {/if}
            {:else if node.kind === 'chance'}
              <label>{t('Chance in percent')}
                <input type="number" min="0" max="100" step="any" bind:value={node.percent} oninput={touch}>
              </label>
              <span class="note">{t('10 % is a chance of 1 in 10.')}</span>
            {:else if node.kind === 'once'}
              <label>{t('Lets through')}
                <select bind:value={node.scope} onchange={touch}>
                  {#each Object.entries(SCOPE_LABEL) as [id, label]}<option value={id}>{label}</option>{/each}
                </select>
              </label>
              <Toggle bind:checked={node.per_player} label={t('For each player')} wide onchange={touch} />
              <span class="note">{t('The first time the flow gets here it goes on at yes, after that at no, until the next match (or leg).')}</span>
            {:else if node.kind === 'pick'}
              <span class="note">{t('Takes one of the next steps by chance. Select a connection to give it a weight.')}</span>
            {:else if node.kind === 'switch'}
              <label>{t('Fact')}
                <select value={node.field} onchange={(e) => setSwitchField(node, e.target.value)}>
                  {#each switchFields as f}<option value={f}>{FIELD_LABEL[f] || f}{f === 'player' || facts.has(f) ? '' : ` (${t('not given by the trigger')})`}</option>{/each}
                </select>
              </label>
              <label>{t('Reads as')}
                <select value={node.mode} onchange={(e) => setSwitchMode(node, e.target.value)}>
                  <option value="values">{t('Values')}</option>
                  <option value="bands">{t('Bands')}</option>
                </select>
              </label>
              <div class="row-edit">
                <div class="row-head">
                  <span>{node.mode === 'bands' ? t('Upper limit of each output') : t('Values of each output')}</span>
                  <button type="button" class="act" onclick={() => addOutput(node)} disabled={node.outputs.length >= MAX_SWITCH_OUTPUTS}>+ {t('Add output')}</button>
                </div>
                <ul class="rows">
                  {#each node.outputs as o, i (o.id)}
                    <li>
                      <span class="share">{i + 1}</span>
                      {#if node.mode === 'bands'}
                        <input type="number" step="any" value={o.limit} aria-label={t('Upper limit')}
                               onchange={(e) => { o.limit = Number(e.target.value) || 0; sortBands(node); }}>
                      {:else}
                        <input type="text" class="wide" value={o.values.join(', ')} placeholder={t('anna, ben')} aria-label={t('Values')}
                               onchange={(e) => setValues(node, o, e.target.value)}>
                      {/if}
                      <button type="button" class="play" onclick={() => removeOutput(node, i)} title={t('Remove')}>✕</button>
                    </li>
                  {/each}
                </ul>
                {#if FIELD_NOTE[node.field]}<span class="note">{FIELD_NOTE[node.field]}</span>{/if}
                <span class="note">
                  {node.mode === 'bands'
                    ? t('A turn takes the first output whose limit it does not exceed; the next output starts where the one before ends. What is above the last limit takes "otherwise".')
                    : t('Takes the output that names the value (any case). A value sits on one output only; everything else takes "otherwise".')}
                </span>
                <span class="note">{t('A missing value takes "otherwise". An output with no connection does nothing.')}</span>
              </div>
            {:else if node.kind === 'achievement'}
              <label>{t('Achievement')}
                <select bind:value={node.achievement} onchange={touch}>
                  <option value="">{t('(none)')}</option>
                  {#each achievements as a}<option value={a.id}>{a.name}</option>{/each}
                </select>
              </label>
              {#if (achievements.find((a) => a.id === node.achievement)?.tiers || 1) > 1}
                <label>{t('From tier')}
                  <input type="number" min="1" max={achievements.find((a) => a.id === node.achievement).tiers} bind:value={node.tier} oninput={touch}>
                </label>
              {/if}
              <span class="note">{t('Yes if the player of the moment has earned it before. What is earned in this very turn does not count yet.')}</span>
            {:else if node.kind === 'player'}
              <label>{t('Players, separated by commas')}
                <input type="text" value={node.names.join(', ')} oninput={(e) => setNames(e.target.value)}>
              </label>
              <span class="note">{t('Empty means any player.')}</span>
            {:else if node.kind === 'call'}
              <label>{t('Call of the voice pack')}
                <input type="text" list="call-keys" maxlength="160" bind:value={node.key} oninput={touch}>
              </label>
              <label>{t('Plays')}
                <select bind:value={node.channel} onchange={touch}>
                  {#each Object.entries(CHANNEL_LABEL) as [id, label]}<option value={id}>{label}</option>{/each}
                </select>
              </label>
              <datalist id="call-keys">{#each data.call_keys as key}<option value={key}></option>{/each}</datalist>
              <span class="note">{t('{player}, {score} and {next} are the name of the player, the score of the turn and the score that passes.')}</span>
            {:else if node.kind === 'sound'}
              <div class="row-edit">
                <div class="row-head">
                  <span>{t('Sounds')}</span>
                  <button type="button" class="act" onclick={() => addSoundFile(node)} disabled={node.files.length >= MAX_SOUND_FILES}>+ {t('Add sound')}</button>
                </div>
                <ul class="rows">
                  {#each node.files as entry, i}
                    <li>
                      <select bind:value={entry.file} onchange={touch} aria-label={t('Sound')}>
                        <option value="">{t('(choose a file)')}</option>
                        {#each library as f}<option value={f.name}>{f.name}</option>{/each}
                        {#if entry.file && !library.some((f) => f.name === entry.file)}
                          <option value={entry.file}>{entry.file} {t('(missing)')}</option>
                        {/if}
                      </select>
                      <input type="number" class="weight" min="1" max="100" step="1" bind:value={entry.weight} oninput={touch} aria-label={t('Weight')}>
                      <span class="share">{shareOf(node, entry)}</span>
                      <button type="button" class="play" onclick={() => preview(entry.file)} disabled={!entry.file} title={t('Preview')}>▶</button>
                      <button type="button" class="play" onclick={() => removeSoundFile(node, i)} title={t('Remove')}>✕</button>
                    </li>
                  {/each}
                </ul>
                <span class="note">{t('One of the sounds is picked each time. A sound with the weight 2 is played twice as often as one with 1.')}</span>
              </div>
              <label>{t('Volume')}
                <input type="range" min="0" max="1.2" step="0.05" bind:value={node.volume} oninput={touch}>
                <span class="percent">{Math.round(node.volume * 100)} %</span>
              </label>
              <label>{t('Plays')}
                <select bind:value={node.channel} onchange={touch}>
                  {#each Object.entries(CHANNEL_LABEL) as [id, label]}<option value={id}>{label}</option>{/each}
                </select>
              </label>
              <Toggle bind:checked={node.replace} label={t('Replaces the call of this moment')} wide onchange={touch} />
            {:else if node.kind === 'overlay'}
              <label>{t('Effect')}
                <select bind:value={node.animation} onchange={touch}>
                  {#each data.animations as a}<option value={a}>{ANIMATION_LABEL[a] || a}</option>{/each}
                </select>
              </label>
              <label>{t('Text')}<input type="text" maxlength="60" bind:value={node.text} oninput={touch}></label>
              <label>{t('Seconds')}<input type="number" min="1" max="15" bind:value={node.seconds} oninput={touch}></label>
              <span class="note">{t('{player} and {score} in the text are replaced.')}</span>
            {:else}
              <label>{t('Seconds')}<input type="number" min="0" max="30" step="0.5" bind:value={node.seconds} oninput={touch}></label>
              <span class="note">{t('What follows runs after the wait and cannot replace a call.')}</span>
            {/if}
            <button type="button" class="act danger" onclick={() => removeNode(node.id)}>{t('Remove node')}</button>
          </div>
        {/if}
        </div>
      {/if}
    </section>
  </div>
{/if}

<style>
  .empty { color: var(--muted); text-align: center; padding: 1.5rem 0; }
  .empty.small { padding: 0.5rem 0; font-size: 0.85rem; }
  .intro { color: var(--muted); font-size: 0.85rem; margin-bottom: 1rem; line-height: 1.45; }
  .message { font-size: 0.85rem; color: var(--yellow); margin-bottom: 0.75rem; }
  .canvas-message {
    position: absolute; left: 0.6rem; right: 0.6rem; bottom: 0.6rem; z-index: 2; text-align: left; cursor: pointer;
    background: var(--glass-bar, rgba(0, 0, 0, 0.7)); border: 1px solid var(--glass-border); border-radius: 6px;
    padding: 0.4rem 0.7rem; font-family: inherit; font-size: 0.82rem; color: var(--yellow);
  }
  .custom-line { display: flex; align-items: center; gap: 0.5rem; margin: 0.45rem 0 0.15rem; font-size: 0.68rem; color: var(--muted); letter-spacing: 0.06em; text-transform: uppercase; }
  .custom-line::after { content: ''; flex: 1; border-top: 1px solid var(--glass-border); }
  .group { margin: 1.3rem 0 0.4rem; padding-top: 0.7rem; border-top: 1px solid var(--glass-border); font-size: 0.95rem; color: var(--text); font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; }
  .group.first { margin-top: 0.5rem; padding-top: 0; border-top: none; }
  .edited { color: var(--yellow); font-size: 0.75rem; }
  .scene-title[readonly] { border-color: transparent; background: none; }
  .layout { display: grid; grid-template-columns: 17rem minmax(0, 1fr); gap: 1rem; align-items: start; }
  @media (max-width: 900px) { .layout { grid-template-columns: 1fr; } }
  aside { display: flex; flex-direction: column; gap: 1rem; }
  .box { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 8px; padding: 0.65rem 0.8rem; }
  .box-head { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.5rem; }
  .box-title { font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; }
  ul { list-style: none; padding: 0; margin: 0; }
  .scene-list li { display: flex; align-items: center; gap: 0.5rem; padding: 0.15rem 0; }
  .scene-list li.current .scene-name { color: var(--accent); font-weight: 700; }
  .scene-name { flex: 1; text-align: left; background: none; border: none; color: var(--text); font-family: inherit; font-size: 0.9rem; cursor: pointer; padding: 0.25rem 0; }
  .file-list li { display: flex; align-items: center; gap: 0.4rem; padding: 0.3rem 0; border-top: 1px solid var(--glass-border); flex-wrap: wrap; }
  .file-list li:first-child { border-top: none; }
  .fname { font-size: 0.82rem; flex: 1; min-width: 6rem; word-break: break-all; }
  .fmeta { font-size: 0.72rem; color: var(--muted); }
  .play { background: none; border: none; cursor: pointer; color: var(--muted); font-size: 0.8rem; padding: 0 0.25rem; }
  .play:hover:not(:disabled) { color: var(--accent); }
  .play:disabled { opacity: 0.3; cursor: default; }
  .upload, .act {
    background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 6px; color: var(--muted);
    padding: 0.2rem 0.65rem; font-family: inherit; font-size: 0.78rem; cursor: pointer;
  }
  .upload:hover, .act:hover:not(:disabled) { border-color: var(--accent); color: var(--text); }
  .act.danger:hover:not(:disabled) { border-color: var(--red); color: var(--red); }
  .act.primary { color: var(--text); border-color: var(--accent); }
  .act:disabled { opacity: 0.45; cursor: default; }
  .upload.busy { opacity: 0.6; cursor: default; }
  .upload input { display: none; }
  input[type="text"], input[type="number"], select {
    background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 6px; color: var(--text);
    padding: 0.35rem 0.55rem; font-family: inherit; font-size: 0.85rem;
  }
  .scene-head { display: flex; align-items: center; gap: 0.6rem; flex-wrap: nowrap; margin-bottom: 0.6rem; }
  .scene-head > :global(*) { flex-shrink: 0; }
  @media (max-width: 760px) { .scene-head { flex-wrap: wrap; } }
  .scene-head :global(.option-row) { margin-bottom: 0; }
  .slot-info { display: inline-block; flex: none; width: 1.65rem; height: 1.15rem; }
  .slot-info.warn :global(.dot) { color: var(--yellow); border-color: var(--yellow); }
  .scene-head > .scene-title { flex: 1 1 8rem; min-width: 4rem; max-width: 30rem; font-weight: 700; font-size: 1rem; }
  .spacer { flex: 1; }
  .dirty { font-size: 0.78rem; color: var(--yellow); }
  .palette { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-bottom: 0.6rem; }
  .canvas {
    position: relative; overflow: hidden; height: 30rem; background: rgba(0, 0, 0, 0.22); border: 1px solid var(--glass-border);
    border-radius: 8px;
  }
  svg { display: block; width: 100%; height: 100%; touch-action: none; user-select: none; }
  .bg { cursor: grab; }
  .marquee { fill: color-mix(in srgb, var(--accent) 15%, transparent); stroke: var(--accent); stroke-width: 1; stroke-dasharray: 4 3; pointer-events: none; }
  .zoom {
    position: absolute; top: 0.5rem; right: 0.5rem; z-index: 1; display: flex; align-items: center; gap: 0.3rem;
  }
  .zoom .icon { display: inline-flex; align-items: center; padding: 0.2rem 0.4rem; }
  .zoom-level { min-width: 2.8rem; text-align: center; font-size: 0.75rem; color: var(--muted); font-variant-numeric: tabular-nums; }
  .canvas-note { position: absolute; top: 0.6rem; left: 0.8rem; z-index: 1; font-size: 0.8rem; color: var(--yellow); pointer-events: none; }
  .canvas-hint { margin-top: 0.3rem; font-size: 0.72rem; color: var(--muted); }
  .editor.focus {
    position: fixed; inset: 0; z-index: 1000; background: var(--bg); padding: 0.8rem 1rem; display: flex; flex-direction: column;
    overflow: hidden;
  }
  .editor.focus .work { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr) 20rem; gap: 0.8rem; grid-template-rows: minmax(0, 1fr) auto; }
  .editor.focus .canvas { height: auto; min-height: 0; grid-row: 1 / span 2; }
  .editor.focus .canvas-hint { display: none; }
  .editor.focus .inspector { grid-column: 2; grid-row: 1; margin-top: 0; align-self: start; max-height: 100%; overflow: auto; flex-direction: column; align-items: stretch; flex-wrap: nowrap; }
  .bg { fill: transparent; }
  .edge { fill: none; stroke: var(--muted); stroke-width: 2; }
  .edge.sel { stroke: var(--accent); stroke-width: 3; }
  .edge.ghost { stroke: var(--accent); stroke-dasharray: 5 4; }
  .edge-x circle { fill: var(--surface); stroke: var(--red); stroke-width: 2; cursor: pointer; }
  .edge-x path { stroke: var(--red); stroke-width: 2; stroke-linecap: round; pointer-events: none; }
  .edge-hit { fill: none; stroke: transparent; stroke-width: 14; cursor: pointer; }
  .node { cursor: grab; outline: none; }
  .node rect { fill: var(--surface); stroke: var(--border); stroke-width: 2; }
  .node.trigger rect { stroke: var(--accent); }
  .node.condition rect { stroke: var(--yellow); }
  .node.action rect { stroke: var(--text); stroke-opacity: 0.55; }
  .node.failed rect { stroke: var(--red); stroke-width: 3; }
  .node.sel rect, .node:focus-visible rect { stroke-width: 3.5; filter: drop-shadow(0 0 6px var(--accent)); }
  .node .title { fill: var(--muted); font-size: 12px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; }
  .node .detail { fill: var(--text); font-size: 14px; font-weight: 600; }
  .port { fill: var(--surface); stroke: var(--muted); stroke-width: 2; }
  .port.out { cursor: crosshair; stroke: var(--accent); fill: var(--accent-soft); }
  .port.out:hover { fill: var(--accent); }
  .row-line { stroke: var(--border); stroke-width: 1; stroke-opacity: 0.6; }
  .row-label { fill: var(--text); font-size: 13px; }
  .port.out.yes { stroke: var(--green); }
  .port.out.no { stroke: var(--red); }
  .branch { font-size: 11px; font-weight: 700; }
  .branch.yes { fill: var(--green); }
  .branch.no { fill: var(--red); }
  .inspector {
    display: flex; flex-wrap: wrap; align-items: flex-end; gap: 0.7rem 1rem; margin-top: 0.7rem;
    background: var(--glass); border: 1px solid var(--glass-border); border-radius: 8px; padding: 0.65rem 0.8rem;
  }
  .inspector label { display: flex; flex-direction: column; gap: 0.2rem; font-size: 0.75rem; color: var(--muted); }
  .insp-title { flex-basis: 100%; font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; }
  .note.warn { color: var(--yellow); }
  .note { font-size: 0.75rem; color: var(--muted); align-self: center; }
  .row-edit { display: flex; flex-direction: column; gap: 0.35rem; flex: 1 1 22rem; min-width: 0; }
  .row-head { display: flex; align-items: center; justify-content: space-between; font-size: 0.75rem; color: var(--muted); }
  .rows { max-height: 9.5rem; overflow-y: auto; }
  .rows li { display: flex; align-items: center; gap: 0.4rem; padding: 0.15rem 0; }
  .rows select { flex: 1; min-width: 0; }
  .rows .weight { width: 4rem; flex: none; }
  .rows .wide, .rows input[type="number"]:not(.weight) { flex: 1; min-width: 0; }
  .share { width: 2.8rem; flex: none; text-align: right; font-size: 0.75rem; color: var(--muted); font-variant-numeric: tabular-nums; }
  .percent { font-size: 0.78rem; color: var(--muted); margin-left: 0.3rem; }
  .inspector :global(.option-row) { margin-bottom: 0; }
</style>
