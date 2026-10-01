<script>
  // Shown on /tv while no match is running: the darts currently on the board
  // (freeplay, warm-up) as dart boxes with a turn total, and the live dartboard.
  import DartBoard from '../../lib/components/DartBoard.svelte';

  let { darts = [] } = $props();

  let total = $derived(darts.reduce((sum, d) => sum + d.points, 0));
</script>

<div class="idle-live">
  <div class="darts-row">
    {#each [0, 1, 2] as i}
      {@const d = darts[i]}
      <div class="dart-box" class:miss={d && d.points === 0}>
        <div class="dlabel">D{i + 1}</div>
        <div class="dval">{d ? (d.points === 0 ? 'Miss' : String(d.field ?? '—').toUpperCase()) : '—'}</div>
        <div class="dsub">{d ? `(${d.points})` : ''}</div>
      </div>
    {/each}
    <div class="turn-total">
      <div class="tlabel">Total</div>
      <div class="tval">{total}</div>
    </div>
  </div>
  <div class="live-board"><DartBoard readonly {darts} /></div>
</div>

<style>
  .idle-live {
    flex: 1; min-height: 0; display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 2vh; padding: 2vh 3vw;
  }
  .darts-row { width: min(100%, 900px); display: grid; grid-template-columns: 1fr 1fr 1fr auto; gap: 1vw; align-items: center; }
  .dart-box {
    background: color-mix(in srgb, var(--surface) 70%, var(--bg));
    border: 1px solid var(--border); border-radius: 12px; padding: 0.6vw 0.8vw; text-align: center;
  }
  .dart-box .dlabel { font-size: clamp(0.6rem, 0.9vw, 1rem); color: var(--muted); margin-bottom: 2px; }
  .dart-box .dval { font-size: clamp(1.2rem, 2.5vw, 3rem); font-weight: 800; }
  .dart-box .dsub { font-size: clamp(0.6rem, 0.9vw, 1rem); color: var(--muted); min-height: 1.2em; }
  .dart-box.miss .dval { color: var(--red); }
  .turn-total { text-align: right; padding-right: 0.5vw; }
  .turn-total .tlabel { font-size: clamp(0.6rem, 0.9vw, 1rem); color: var(--muted); }
  .turn-total .tval {
    font-size: clamp(1.5rem, 3.5vw, 4rem); font-weight: 800; color: var(--yellow);
    text-shadow: 0 0 28px color-mix(in srgb, var(--yellow) 35%, transparent);
  }
  .live-board { width: min(100%, 900px); --board-max: min(100%, 62vh); display: flex; justify-content: center; }
</style>
