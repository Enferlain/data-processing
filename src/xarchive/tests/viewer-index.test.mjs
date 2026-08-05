import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const viewerHtml = readFileSync(new URL('../viewer.html', import.meta.url), 'utf8');
const inlineScript = viewerHtml.match(/<script>([\s\S]*?)<\/script>/)?.[1];

if (!inlineScript) {
  throw new Error('Could not find the viewer inline script');
}

// Initialization needs a browser. The index-building code can run in a small
// VM context, which keeps this regression test dependency-free.
const viewerCode = inlineScript.replace(/\/\/ ---- Start ----[\s\S]*$/, '');

function createViewerContext() {
  const element = {
    addEventListener() {},
    classList: { add() {}, remove() {}, toggle() {} },
    style: {},
    value: '',
  };
  const context = vm.createContext({
    clearTimeout() {},
    console,
    document: {
      activeElement: null,
      addEventListener() {},
      getElementById() { return element; },
    },
    navigator: { userAgent: 'node-test' },
    setTimeout() { return 0; },
    URL,
    window: { location: { href: 'file:///viewer.html', protocol: 'file:' } },
  });

  vm.runInContext(viewerCode, context);
  vm.runInContext(`
    sleep = async () => {};
    renderFolders = () => {};
    applyFilters = () => {};
  `, context);
  return context;
}

async function processData(context, data) {
  context.testData = data;
  await vm.runInContext('processData(testData)', context);
  delete context.testData;
}

function snapshotIndices(context) {
  return JSON.parse(vm.runInContext(`JSON.stringify({
    constructorFolder: folderMap.get('constructor'),
    protoFolder: folderMap.get('__proto__'),
    toStringFolder: folderMap.get('toString'),
    constructorSearch: Array.from(searchBookmarks('constructor')),
    protoSearch: Array.from(searchBookmarks('__proto__')),
    ordinarySearch: Array.from(searchBookmarks('ordinary')),
  })`, context));
}

test('viewer indexes names that collide with Object prototype properties', async () => {
  const context = createViewerContext();
  await processData(context, {
    folders: [
      { name: 'constructor' },
      { name: '__proto__' },
      { name: 'toString' },
    ],
    bookmarks: [
      {
        created_at: '2026-04-29T00:00:00.000Z',
        folders: ['constructor', '__proto__', 'toString'],
        full_text: 'constructor __proto__ ordinary',
      },
    ],
  });

  assert.deepEqual(snapshotIndices(context), {
    constructorFolder: [0],
    protoFolder: [0],
    toStringFolder: [0],
    constructorSearch: [0],
    protoSearch: [0],
    ordinarySearch: [0],
  });
});

test('viewer handles a colliding token late in a 30,000-bookmark export', async () => {
  const context = createViewerContext();
  const bookmarks = Array.from({ length: 30_000 }, (_, index) => ({
    created_at: '2026-04-29T00:00:00.000Z',
    full_text: index === 29_999
      ? `bookmark ${index} constructor __proto__`
      : `bookmark ${index}`,
  }));

  await processData(context, { folders: [], bookmarks });

  const result = JSON.parse(vm.runInContext(`JSON.stringify({
    constructor: Array.from(searchBookmarks('constructor')),
    proto: Array.from(searchBookmarks('__proto__')),
  })`, context));

  assert.deepEqual(result, { constructor: [29_999], proto: [29_999] });
});

test('retrying after a failed load starts with fresh indices', async () => {
  const context = createViewerContext();
  await processData(context, {
    folders: [],
    bookmarks: [{ created_at: '2026-04-29T00:00:00.000Z', full_text: 'firstonly' }],
  });
  await processData(context, {
    folders: [],
    bookmarks: [{ created_at: '2026-04-30T00:00:00.000Z', full_text: 'secondonly' }],
  });

  const result = JSON.parse(vm.runInContext(`JSON.stringify({
    first: Array.from(searchBookmarks('firstonly')),
    second: Array.from(searchBookmarks('secondonly')),
  })`, context));

  assert.deepEqual(result, { first: [], second: [0] });
});
