<script>
  import { describePosition } from './boardPosition.js'
  export let board = []
  export let hands = {}
  export let currentPlayer = 'black'
  let includeEmpty = false
  $: position = describePosition(board, hands, currentPlayer, includeEmpty)
</script>

<details class="position-text">
  <summary>Position as text</summary>
  <p>{position.currentPlayer} to move</p>
  {#each position.held as hand}<p>{hand.side} hand: {hand.pieces}</p>{/each}
  <label><input type="checkbox" bind:checked={includeEmpty} /> Include empty squares</label>
  <table>
    <caption>Displayed position</caption>
    <thead><tr><th scope="col">Square</th><th scope="col">Side</th><th scope="col">Piece</th></tr></thead>
    <tbody>{#each position.squares as square}<tr><th scope="row">{square.coordinate}</th><td>{square.side || '—'}</td><td>{square.piece}</td></tr>{/each}</tbody>
  </table>
</details>

<style>
  .position-text { margin-top: 8px; font-size: 13px; border: 1px solid var(--border); border-radius: 6px; padding: 0 10px; }
  summary { min-height: 44px; padding: 12px 0; cursor: pointer; font-weight: 600; }
  p { margin: 6px 0; overflow-wrap: anywhere; }
  label { display: flex; align-items: center; gap: 8px; min-height: 44px; }
  table { width: 100%; border-collapse: collapse; margin: 8px 0; }
  caption { text-align: left; margin-bottom: 6px; }
  th, td { text-align: left; padding: 6px; border-bottom: 1px solid var(--border); }
</style>
