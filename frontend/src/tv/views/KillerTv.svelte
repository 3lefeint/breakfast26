<script>
  // Live Killer. The board is the stage: the field of every player's number is colored in the player's
  // color for the whole game, and the board shows what is open for whoever is up: the double of the
  // own number while they are no killer yet, then the fields that take a life from each opponent,
  // in the color of its owner. Beside it: the players with number, lives and status, the darts of the
  // turn (tap one to correct it) and what they did.
  import { flip } from 'svelte/animate';
  import { cap } from '../../lib/util.js';
  import { api } from '../../lib/api.js';
  import { ruleChips, dartLabel, eventText, boardZones } from '../../lib/killer.js';
  import LivesDisplay from '../../lib/components/LivesDisplay.svelte';
  import DartBoard from '../../lib/components/DartBoard.svelte';
  import DartCorrectModal from './DartCorrectModal.svelte';

  let { killer } = $props();

  let me = $derived((killer.players || []).find((p) => p.current) || null);
  let darts = $derived(killer.darts || []);
  let markers = $derived(darts.map((d, i) => ({ n: i + 1, x: d.x, y: d.y, color: me?.color, ring: me?.ring })));
  let events = $derived(killer.turn_events || []);
  let livesMax = $derived(killer.lives_max || 3);
  let correctingIndex = $state(null);

  function ringStyle(p) {
    return p.ring ? `outline: 3px ${p.ring.dash ? 'dashed' : 'solid'} ${p.ring.color}; outline-offset: 1px;` : '';
  }

  function openCorrect(index) {
    if (killer.state !== 'playing' || darts[index] == null) return;
    correctingIndex = index;
  }

  async function stop() {
    if (!confirm('Stop the current game?')) return;
    await api('POST', '/api/killer/stop');
    window.location.href = '/';
  }

  async function undo() {
    if (!confirm('Undo the last completed turn?')) return;
    await api('POST', '/api/killer/undo');
  }
</script>

<div class="stage">
  <div class="bar">
    <div class="turn">
      <span class="swatch" style="background: {me?.color || 'var(--muted)'}; {me ? ringStyle(me) : ''}"></span>
      <span class="turn-name">{cap(killer.current_player || '—')}</span>
    </div>
    <div class="rules">
      {#each ruleChips(killer) as chip}<span class="rule-chip">{chip}</span>{/each}
    </div>
  </div>

  <div class="body">
    <div class="board-col">
      <DartBoard readonly darts={markers} zones={boardZones(killer)} />
    </div>

    <div class="side">
      <ul class="k-list">
        {#each killer.players as p (p.name)}
          <li class:current-row={p.current} class:out={p.out} animate:flip={{ duration: 300 }}>
            <span class="row-name">
              <span class="swatch" style="background: {p.color || 'var(--muted)'}; {ringStyle(p)}"></span>
              <span class="name">{cap(p.name)}</span>
            </span>
            <span class="slot">
              {#if p.out}
                <span class="tag">OUT</span>
              {:else if p.killer}
                <span class="tag killer">KILLER</span>
              {:else}
                <span class="num">{p.number}</span>
              {/if}
            </span>
            <span class="lives">{#if !p.out}<LivesDisplay lives={p.lives} {livesMax} />{/if}</span>
          </li>
        {/each}
      </ul>

      <div class="darts-row">
        {#each [0, 1, 2] as i}
          <button type="button" class="dart-box" class:miss={darts[i] && dartLabel(darts[i]) === 'Miss'}
                  disabled={darts[i] == null} onclick={() => openCorrect(i)}>
            <span class="dlabel">D{i + 1}</span>
            <span class="dval">{darts[i] ? dartLabel(darts[i]) : '—'}</span>
          </button>
        {/each}
      </div>

      <ul class="events">
        {#each events as e}
          <li class={e.kind}>{eventText(e)}</li>
        {/each}
      </ul>

      <div class="endgame-row">
        <button class="btn-end-game" onclick={undo}>↩ Undo</button>
        <button class="btn-end-game" onclick={stop}>■ Stop</button>
      </div>
    </div>
  </div>
</div>

{#if correctingIndex != null}
  <DartCorrectModal dartIndex={correctingIndex} onClose={() => (correctingIndex = null)}
                    endpoint="/api/killer/correct-dart" />
{/if}

<style>
  .stage {
    flex: 1; min-width: 0; min-height: 0; display: flex; flex-direction: column;
    background: linear-gradient(165deg, color-mix(in srgb, var(--accent) 8%, transparent), transparent 55%);
  }
  .bar { display: flex; align-items: center; justify-content: space-between; gap: 2vw; padding: 1vw 3vw 0.4vw; flex-wrap: wrap; }
  .turn { display: flex; align-items: baseline; gap: 1vw; flex-wrap: wrap; min-width: 0; }
  .turn .swatch { align-self: center; width: 1.2em; height: 1.2em; font-size: clamp(1.4rem, 3vw, 3rem); }
  .turn-name { font-size: clamp(1.6rem, 3.6vw, 3.6rem); font-weight: 900; text-transform: uppercase; letter-spacing: 0.06em; }
  .rules { display: flex; flex-wrap: wrap; gap: 0.4rem; }
  .rule-chip { font-size: clamp(0.65rem, 1vw, 1rem); color: var(--muted); border: 1px solid var(--border); border-radius: 999px; padding: 0.1em 0.7em; }

  .body { flex: 1; min-height: 0; display: flex; gap: 2vw; padding: 0 2vw 1vw 2vw; }
  .board-col {
    flex: 1; min-width: 0; display: flex; align-items: center; justify-content: center;
    --board-max: min(calc(100vh - 215px), 60vw);
  }
  .side { flex: 0 0 clamp(340px, 36vw, 640px); min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 1.2vw; }

  .k-list { list-style: none; padding: 0; margin: 0; }
  .k-list li {
    display: grid; grid-template-columns: 1fr 5.5em auto; align-items: center; gap: 1vw;
    padding: 0.5vw 1vw; margin-top: 0.5vw; border-radius: 10px;
    font-size: clamp(0.9rem, 1.6vw, 1.9rem); border: 1px solid transparent; transition: background 0.2s;
  }
  .k-list li:first-child { margin-top: 0; }
  .current-row {
    background: linear-gradient(90deg, color-mix(in srgb, var(--green) 14%, transparent), transparent);
    border-color: color-mix(in srgb, var(--green) 25%, transparent) !important;
  }
  .current-row .name { color: var(--green); font-weight: 700; }
  .k-list li.out { opacity: 0.45; }
  .k-list li.out .name { text-decoration: line-through; }
  .row-name { display: flex; align-items: center; gap: 0.7em; min-width: 0; }
  .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .swatch { width: 0.9em; height: 0.9em; border-radius: 50%; flex-shrink: 0; }
  .slot { display: flex; justify-content: center; }
  .num { font-weight: 900; color: var(--muted); }
  .lives { display: flex; justify-content: flex-end; min-width: 3.2em; }
  .tag { font-size: 0.6em; font-weight: 800; letter-spacing: 0.04em; color: var(--muted); border: 1px solid var(--border); border-radius: 999px; padding: 0 0.6em; white-space: nowrap; }
  .tag.killer { color: var(--red); border-color: color-mix(in srgb, var(--red) 55%, transparent); background: color-mix(in srgb, var(--red) 14%, var(--surface)); }

  .darts-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 0.8vw; }
  .dart-box {
    display: flex; flex-direction: column; align-items: center;
    background: color-mix(in srgb, var(--surface) 70%, var(--bg)); border: 1px solid var(--border); border-radius: 12px;
    padding: 0.5vw 0.8vw; font-family: inherit; color: inherit; cursor: pointer;
    transition: border-color 0.15s, transform 0.15s;
  }
  .dart-box:disabled { cursor: default; color: var(--muted); }
  .dart-box:not(:disabled):hover { border-color: var(--accent); transform: translateY(-2px); }
  .dlabel { font-size: clamp(0.6rem, 0.9vw, 1rem); color: var(--muted); }
  .dval { font-size: clamp(1.1rem, 2.2vw, 2.6rem); font-weight: 800; }
  .dart-box.miss .dval { color: var(--muted); }

  .events { list-style: none; padding: 0; margin: 0; min-height: 3.2em; font-size: clamp(0.85rem, 1.4vw, 1.5rem); }
  .events li { padding: 0.12em 0; color: var(--muted); }
  .events li.killer, .events li.out { color: var(--red); font-weight: 700; }
  .events li.hit, .events li.own_goal { color: var(--yellow); font-weight: 700; }

  .endgame-row { display: flex; gap: 0.6rem; margin-top: auto; }
  .btn-end-game {
    background: var(--surface); border: 1px solid var(--border); color: var(--muted);
    border-radius: 999px; padding: 0.55rem 1.25rem;
    font-size: clamp(0.8rem, 1.3vw, 1rem); font-weight: 600; cursor: pointer;
    transition: border-color 0.15s, color 0.15s, background 0.15s;
  }
  .btn-end-game:hover { border-color: var(--red); color: var(--red); background: rgba(248, 113, 113, 0.08); }
</style>
