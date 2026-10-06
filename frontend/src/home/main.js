import { mount } from 'svelte';
import '../lib/theme.css';
import { initLanguage } from '../lib/i18n.js';

// The language is loaded before the app's modules are evaluated, so texts in module-level
// constants are already translated.
const app = initLanguage()
  .then(() => import('./App.svelte'))
  .then(({ default: App }) => mount(App, { target: document.getElementById('app') }));

export default app;
