// Usage: node scripts/mermaid-lint/lint.mjs README.md docs/*.md
// Parses each ```mermaid block with Mermaid's own parser (jsdom stands in for the browser) and
// prints file:line for any that fail. Syntax only: it does not render or check layout.
import { JSDOM } from 'jsdom';
import fs from 'node:fs';
const dom = new JSDOM('<!doctype html><body></body>');
for (const k of ['window','document','Element','HTMLElement','SVGElement','Node','DOMParser','NodeFilter']) {
  const v = k === 'window' ? dom.window : dom.window[k];
  try { Object.defineProperty(globalThis, k, { value: v, configurable: true, writable: true }); } catch {}
}
const { default: mermaid } = await import('mermaid');
let bad = 0;
for (const f of process.argv.slice(2)) {
  const md = fs.readFileSync(f, 'utf8');
  for (const m of md.matchAll(/^```mermaid\n([\s\S]*?)^```/gm)) {
    const line = md.slice(0, m.index).split('\n').length;
    try { await mermaid.parse(m[1]); }
    catch (e) { bad++; console.log(`${f}:${line}: ${String(e.message).split('\n').slice(0,3).join(' | ')}`); }
  }
}
console.log(bad ? `${bad} invalid` : 'all mermaid blocks valid'); process.exit(bad?1:0);
