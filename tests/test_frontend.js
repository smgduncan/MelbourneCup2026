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

  const previousRows = node("#odds-rows").innerHTML;
  fail = true;
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
  console.log("Frontend checks passed: initial load, uncached button refresh, failure retention, offline fallback.");
})().catch(error => { console.error(error); process.exitCode = 1; });
