// Translations for the interface. The English text is the key: `t` returns it as it
// is for English and looks it up in the table of the language otherwise, so a missing
// translation shows the English text. `{name}` in a text is replaced from `params`.
//
// The language is one setting per installation (`[web] language`), read once before the app
// is mounted. A change in Settings reloads the page, so `t` is a plain function and also
// works in constants that are evaluated once.
import de from './locales/de.js';

const TABLES = { de };

export let language = 'en';
let table = {};

export async function initLanguage() {
  try {
    const res = await fetch('/api/language').then((r) => r.json());
    if (res.language && (res.language === 'en' || TABLES[res.language])) language = res.language;
  } catch (_) {
    // no backend answer: keep English
  }
  table = TABLES[language] || {};
  document.documentElement.lang = language;
}

export function t(text, params) {
  const out = table[text] ?? text;
  if (!params) return out;
  return out.replace(/\{(\w+)\}/g, (m, key) => (key in params ? params[key] : m));
}
