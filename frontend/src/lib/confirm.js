import { writable } from 'svelte/store';

// The question of the open confirmation dialog ({ message, resolve }), null while none is open.
export const confirmRequest = writable(null);

// Asks the user to confirm an action in the app's own dialog instead of the browser's.
// Resolves true on Yes, false on No, Escape or a click next to the dialog.
export function confirmDialog(message) {
  return ask(message, false);
}

// Tells the user something in the same dialog, with a single OK button. Resolves once it is closed.
export function alertDialog(message) {
  return ask(message, true);
}

// A question with two answers that have their own labels. Escape and a click next to the dialog do not answer it:
// it stays open until one of the buttons is pressed. Closed by something else (`answerConfirm(null)`, another dialog)
// it resolves null.
export function choiceDialog(message, yes, no) {
  return ask(message, false, { yes, no, modal: true });
}

function ask(message, info, options = {}) {
  return new Promise((resolve) => {
    confirmRequest.update((open) => {
      if (open) open.resolve(open.modal ? null : false);
      return { message, info, resolve, ...options };
    });
  });
}

export function answerConfirm(answer) {
  confirmRequest.update((open) => {
    if (open) open.resolve(answer);
    return null;
  });
}
