import { apiJson } from './api.js';

// Opens a voice chat in its own tab. The page lives on the relay (HTTPS, so the browser allows the microphone). The tab is
// opened first, in the click, so a pop-up blocker lets it through; it is sent to the address once the backend has it.
// Resolves {error}, {url, blocked: true} when no tab could be opened, or {}.
async function openIn(path) {
  const tab = window.open('about:blank', 'breakfast-voice');
  const res = await apiJson('POST', path).catch(() => ({ error: 'Breakfast did not answer' }));
  if (res.error || !res.url) {
    if (tab) tab.close();
    return { error: res.error || 'Breakfast did not answer' };
  }
  if (!tab) return { url: res.url, blocked: true };
  tab.opener = null;
  tab.location.href = res.url;
  return {};
}

// The voice chat of the open online match.
export const openVoiceChat = () => openIn('/api/online/voice');

// A voice chat channel of the circle, without a match.
export const openVoiceChannel = (id) => openIn(`/api/voice/channels/${encodeURIComponent(id)}/open`);
