import { confirmDialog, pinDialog, alertDialog } from './confirm.js';
import { apiJson } from './api.js';
import { t } from './i18n.js';

// A delete that cannot be undone: asks first, then for the PIN of this location when one is set, and sends
// `DELETE url`. Resolves true once the server did it; a refusal is shown in a dialog and resolves false.
export async function deleteGuarded(url, message) {
  if (!(await confirmDialog(message))) return false;
  const { pin_required: needsPin } = await apiJson('GET', '/api/delete-guard');
  const headers = {};
  if (needsPin) {
    const pin = await pinDialog(t('Enter your PIN'));
    if (pin == null) return false;
    headers['X-Pin'] = pin;
  }
  let answer;
  try {
    answer = await (await fetch(url, { method: 'DELETE', headers })).json();
  } catch (e) {
    answer = { error: String(e) };
  }
  if (answer.error) {
    await alertDialog(answer.error);
    return false;
  }
  window.dispatchEvent(new Event('stats-changed'));
  return true;
}
