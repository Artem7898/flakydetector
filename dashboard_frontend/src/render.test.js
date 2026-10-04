/** A real React SSR contract test. This is deliberately not called browser E2E. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile, readdir, mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {validateAnalysis} from './contract.js';

test('every accepted backend fixture renders with real ReactDOMServer', async context => {
  let build;
  try { ({build} = await import('esbuild')); }
  catch (error) {
    if (error.code !== 'ERR_MODULE_NOT_FOUND' || process.env.REQUIRE_RENDER_TESTS === '1') throw error;
    context.skip('npm dependencies are unavailable; run npm ci before the real React render gate');
    return;
  }
  const directory = await mkdtemp(join(tmpdir(), 'flaky-real-react-'));
  try {
    const outfile = join(directory, 'render.cjs');
    const component = fileURLToPath(new URL('./Results.jsx', import.meta.url));
    await build({
      stdin: {contents: `import React from 'react';
        import {renderToString} from 'react-dom/server';
        import Results from ${JSON.stringify(component)};
        export function render(payload) {
          return renderToString(<Results payload={payload} snapshot={{fileName:'captured',useMl:false}} stale={false}/>);
        }`, loader: 'jsx', resolveDir: fileURLToPath(new URL('../', import.meta.url))},
      bundle: true, platform: 'node', format: 'cjs', jsx: 'automatic', outfile,
    });
    const {render} = await import(pathToFileURL(outfile).href);
    const names = await readdir(new URL('./fixtures/', import.meta.url));
    for (const name of names) {
      const payload = validateAnalysis(JSON.parse(await readFile(new URL(`./fixtures/${name}`, import.meta.url), 'utf8')));
      const html = render(payload);
      assert.ok(html.includes('Evidence, not a guess'), name);
      assert.ok(!html.includes('NaN'), name);
    }
  } finally { await rm(directory, {recursive: true, force: true}); }
});
