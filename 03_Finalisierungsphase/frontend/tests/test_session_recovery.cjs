/* Run from phase3: node frontend/tests/test_session_recovery.cjs
 * Native Node.js only. Exercises the actual production functions in a VM
 * with controlled transport responses; this is not a browser test.
 */
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
function between(startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start + startMarker.length);
  assert.ok(start >= 0 && end > start, `Production function boundary missing: ${startMarker}`);
  return source.slice(start, end);
}
const productionFunctions = between('  async function api(', '  function bindSubmit(')
  + between('  async function loadSession()', '  (async () => {');

function setup(fetcher) {
  const state = {
    user: { user_id: 1 }, addresses: [{}], csrf: 'old-token',
    sessionReady: true, sessionSequence: 7,
  };
  const calls = [];
  const snapshots = [];
  const context = {
    state,
    dialog: { open: false },
    async fetch(url, options) { calls.push({ url, options }); return fetcher(url, options); },
    closeDialog() {},
    renderAccount() { snapshots.push({ ready: state.sessionReady, csrf: state.csrf, user: state.user }); },
    renderAddressPicker() {},
    renderLoginStates() {},
    notice() {},
    empty() {},
    button() {},
    $() { return { firstChild: { append() {} } }; },
    async applySession(data) {
      state.user = data.user;
      state.csrf = data.csrf_token;
      state.sessionReady = true;
      state.sessionSequence++;
    },
  };
  vm.createContext(context);
  vm.runInContext(productionFunctions + '\nglobalThis.apiCall = api;', context);
  return { context, state, calls, snapshots };
}
function response(status, data) {
  return { status, ok: status >= 200 && status < 300, async json() { return data; } };
}
function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

async function recoversTokenWithoutRepeatingMutation() {
  const test = setup(async url => url === '/api/session'
    ? response(200, { user: null, csrf_token: 'anonymous-token', addresses: [] })
    : response(401, { error: 'Sitzung abgelaufen' }));
  await assert.rejects(test.context.apiCall('/api/books', {
    method: 'POST', body: { title: 'Test' },
  }), /Sitzung abgelaufen/);
  assert.equal(test.calls.length, 2);
  assert.equal(test.calls[0].options.method, 'POST');
  assert.equal(test.calls[1].url, '/api/session');
  assert.equal(test.calls[1].options.method, 'GET');
  assert.equal(test.state.csrf, 'anonymous-token');
  assert.equal(test.state.sessionReady, true);
  assert.equal(test.snapshots[0].ready, false);
  assert.equal(test.snapshots[0].csrf, '');
}

async function failedRecoveryDoesNotRecurse() {
  const test = setup(async () => response(401, { error: 'Nicht angemeldet' }));
  await assert.rejects(test.context.apiCall('/api/loans'), /Nicht angemeldet/);
  assert.equal(test.calls.length, 2);
  assert.equal(test.calls[1].url, '/api/session');
  assert.equal(test.state.sessionReady, false);
  assert.equal(test.state.csrf, '');
}

async function staleRecoveryPreservesNewLogin() {
  const pending = deferred();
  const started = deferred();
  const test = setup(async url => {
    if (url === '/api/session') { started.resolve(); return pending.promise; }
    return response(401, { error: 'Abgelaufen' });
  });
  const expired = test.context.apiCall('/api/loans').catch(error => error.message);
  await started.promise;
  test.state.user = { user_id: 2 };
  test.state.csrf = 'new-login-token';
  test.state.sessionReady = true;
  test.state.sessionSequence++;
  pending.resolve(response(200, { user: null, csrf_token: 'stale-anonymous-token', addresses: [] }));
  assert.equal(await expired, 'Abgelaufen');
  assert.equal(test.state.user.user_id, 2);
  assert.equal(test.state.csrf, 'new-login-token');
  assert.equal(test.state.sessionReady, true);
}

async function staleUnauthorizedResponsePreservesNewLogin() {
  const pending = deferred();
  const test = setup(() => pending.promise);
  const stale = test.context.apiCall('/api/my-books').catch(error => error.message);
  test.state.user = { user_id: 3 };
  test.state.csrf = 'latest-token';
  test.state.sessionSequence++;
  pending.resolve(response(401, { error: 'Alte Sitzung' }));
  assert.equal(await stale, 'Alte Sitzung');
  assert.equal(test.calls.length, 1);
  assert.equal(test.state.user.user_id, 3);
  assert.equal(test.state.csrf, 'latest-token');
}

(async () => {
  const tests = [
    recoversTokenWithoutRepeatingMutation,
    failedRecoveryDoesNotRecurse,
    staleRecoveryPreservesNewLogin,
    staleUnauthorizedResponsePreservesNewLogin,
  ];
  for (const test of tests) {
    await test();
    process.stdout.write(`PASS ${test.name}\n`);
  }
  process.stdout.write(`${tests.length} session recovery checks passed.\n`);
})().catch(error => {
  process.stderr.write(`${error.stack}\n`);
  process.exitCode = 1;
});
