// Run with: node tests/test_frontend.js
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");
const fixture = JSON.parse(fs.readFileSync(path.join(root, "public/data.json"), "utf8"));
const elements = new Map();
const calls = [];
let fail = false;
let fallbackOnly = false;
const node = (selector) => {
  if (!elements.has(selector)) elements.set(selector, {
    value: "soft", hidden: true, disabled: false, textContent: "", innerHTML: "",
    handlers: {}, classList: { toggle() {} }, setAttribute() {},
    addEventListener(event, callback) { this.handlers[event] = callback; }
  });
  return elements.get(selector);
};
const context = vm.createContext({
  document: { querySelector: node }, URL, URLSearchParams, Intl, console,
  fetch: async (url, options) => {
    calls.push({ url, options });
    if (fail || (fallbackOnly && url !== "/data.json")) throw new Error("Test offline");
    if (url === "/api/reload") return { ok: true, json: async () => ({
      updated: ["GoBet selections"], sources: [], note: "Other providers were not updated."
    }) };
    return { ok: true, json: async () => JSON.parse(JSON.stringify(fixture)) };
  }
});
const flush = () => new Promise(resolve => setImmediate(resolve));

(async () => {
  const source = fs.readFileSync(path.join(root, "public/app.js"), "utf8");
  vm.runInContext(source, context);
  await flush();
  assert.match(node("#connection-state").textContent, /Connected to Atlas/);
  assert.match(node("#odds-rows").innerHTML, /Trustyourinstinct/);
  assert.match(node("#tipster-details-count").textContent, /19/);

  await node("#refresh-button").handlers.click();
  const refreshCall = calls.at(-1);
  assert.equal(refreshCall.url, "/api/analysis");
  assert.equal(refreshCall.options.method, "POST");
  assert.equal(refreshCall.options.cache, "no-store");
  assert.equal(JSON.parse(refreshCall.options.body).budget, 100);
  assert.equal(node("#refresh-button").disabled, false);
  assert.match(node("#connection-state").textContent, /refreshed/);

  const event = { preventDefault() {} };
  const countBefore = calls.length;
  node("#reload-key").value = "";
  await node("#provider-reload-form").handlers.submit(event);
  assert.equal(calls.length, countBefore);

  const key = "test-key-not-real-" + "x".repeat(32);
  node("#reload-key").value = key;
  node("#reload-confirm").checked = true;
  await node("#provider-reload-form").handlers.submit(event);
  const reloadCall = calls.find((call) => call.url === "/api/reload");
  assert.equal(reloadCall.options.method, "POST");
  assert.equal(reloadCall.options.headers.Authorization, `Bearer ${key}`);
  assert.equal(JSON.parse(reloadCall.options.body).confirm, true);
  assert.equal(node("#reload-key").value, "");
  assert.equal(node("#reload-confirm").checked, false);
  assert.equal(node("#reload-button").disabled, false);
  assert.equal(calls.at(-1).url, "/api/analysis");
  assert.match(node("#reload-status").textContent, /Saved: GoBet selections/);
  assert(!node("#reload-status").textContent.includes(key));

  const previousRows = node("#odds-rows").innerHTML;
  fail = true;
  node("#reload-key").value = key;
  node("#reload-confirm").checked = true;
  await node("#provider-reload-form").handlers.submit(event);
  assert.match(node("#reload-status").textContent, /Reload failed/);
  assert.equal(node("#reload-key").value, "");
  assert.equal(node("#odds-rows").innerHTML, previousRows);
  await node("#refresh-button").handlers.click();
  assert.equal(node("#odds-rows").innerHTML, previousRows);
  assert.equal(node("#refresh-button").disabled, false);
  assert.equal(node("#page-error").hidden, false);
  assert.match(node("#connection-state").textContent, /Refresh failed/);

  fail = false;
  fallbackOnly = true;
  vm.runInContext(source, context);
  await flush();
  assert.match(node("#connection-state").textContent, /saved snapshot/);
  assert.match(node("#page-error").textContent, /last exported snapshot/);
  assert.match(node("#pick-cards").innerHTML, /Trustyourinstinct/);
  console.log("Frontend checks passed: initial load, refresh, admin provider import, key clearing, failure retention, offline fallback.");
})().catch(error => { console.error(error); process.exitCode = 1; });
