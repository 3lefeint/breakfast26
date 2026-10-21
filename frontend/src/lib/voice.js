import { apiJson } from './api.js';

// Opens the voice chat of the open online match in its own tab. The page lives on the relay (HTTPS, so the browser
// allows the microphone). The tab is opened first, in the click, so a pop-up blocker lets it through; it is sent to
// the address once the backend has it. Resolves {error}, {url, blocked: true} when no tab could be opened, or {}.
export async function openVoiceChat() {
  const tab = window.open('about:blank', 'breakfast-voice');
  const res = await apiJson('POST', '/api/online/voice').catch(() => ({ error: 'Breakfast did not answer' }));
  if (res.error || !res.url) {
    if (tab) tab.close();
    return { error: res.error || 'Breakfast did not answer' };
  }
  if (!tab) return { url: res.url, blocked: true };
  tab.opener = null;
  tab.location.href = res.url;
  return {};
}
