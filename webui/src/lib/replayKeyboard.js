export function replayAction(event) {
  if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return null
  if (event.target?.isContentEditable || event.target?.closest?.('button, a, input, select, textarea, summary, [contenteditable]:not([contenteditable="false"]), [role="button"], [role="tab"], [role="log"], [role="slider"], [role="link"], [role="switch"], [role="checkbox"], [role="radio"], [role="combobox"], [role="listbox"], [role="menuitem"], [role="textbox"], [data-move-log]')) return null
  if (event.key === 'ArrowLeft') return { step: event.shiftKey ? -5 : -1 }
  if (event.key === 'ArrowRight') return { step: event.shiftKey ? 5 : 1 }
  return { Home: 'first', End: 'follow', ' ': 'pause', h: 'heatmap', H: 'heatmap' }[event.key] || null
}
