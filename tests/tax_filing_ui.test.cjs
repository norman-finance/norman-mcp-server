const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");

// Exercise the shipped inline script and host notifications without a browser
// or a real API. No binding tool is called during these rendering transitions.
function app() {
  const script = readFileSync(join(__dirname, "../norman_mcp/apps/tax_filing.html"), "utf8")
    .match(/<script>([\s\S]*?)<\/script>/)[1];
  const element = () => ({
    innerHTML: "", textContent: "", dataset: {}, listeners: {},
    classList: { toggle() {} },
    addEventListener(name, handler) { this.listeners[name] = handler; },
  });
  const elements = Object.fromEntries(
    ["title", "content", "loading", "ask", "confirm", "submit"].map(id => [id, element()]),
  );
  const tabs = ["preview", "submission"].map(section => ({ ...element(), dataset: { section } }));
  const calls = [];
  const listeners = {};
  const parent = { postMessage(message) { calls.push(message); } };
  const window = {
    parent,
    addEventListener(name, handler) { listeners[name] = handler; },
  };
  const document = {
    documentElement: { lang: "en" },
    getElementById(id) { return elements[id]; },
    querySelectorAll(selector) { return selector === ".tab" ? tabs : []; },
  };
  vm.runInNewContext(script, { window, document, setTimeout() {}, clearTimeout() {} });
  return {
    elements, tabs, calls,
    update(data, meta = {}) {
      listeners.message({ source: parent, data: {
        jsonrpc: "2.0", method: "ui/notifications/tool-result",
        params: { structuredContent: data, _meta: meta },
      } });
    },
  };
}

function preview(overrides = {}) {
  return {
    report: { id: "synthetic-report", submitted: false },
    section: "preview", items: [], canSubmit: true,
    preview: { available: true, downloadUrl: "https://example.test/preview.pdf", error: "" },
    ...overrides,
  };
}

test("PDF without thumbnail remains reviewable and still needs explicit confirmation", () => {
  const ui = app();
  ui.update(preview());
  assert.match(ui.elements.content.innerHTML, /Download PDF/);
  assert.match(ui.elements.content.innerHTML, /The test PDF is ready/);
  assert.doesNotMatch(ui.elements.content.innerHTML, /Resolve the reported issue/);

  ui.tabs[1].listeners.click();
  assert.match(ui.elements.content.innerHTML, /id="submit"[^>]*disabled/);
  ui.elements.confirm.listeners.change({ target: { checked: true } });
  assert.doesNotMatch(ui.elements.content.innerHTML, /id="submit"[^>]*disabled/);

  ui.update(preview({ section: "submission" }));
  assert.match(ui.elements.content.innerHTML, /id="submit"[^>]*disabled/);
  assert.equal(ui.calls.filter(call => call.method === "tools/call").length, 0);
});

test("a refreshed preview cannot reuse a previous thumbnail", () => {
  const ui = app();
  ui.update(preview(), { "norman/previewImage": "old-thumbnail" });
  assert.match(ui.elements.content.innerHTML, /old-thumbnail/);
  ui.update(preview());
  assert.doesNotMatch(ui.elements.content.innerHTML, /old-thumbnail|<img/);
  assert.match(ui.elements.content.innerHTML, /The test PDF is ready/);
});

test("a failed preview clears the old image and keeps submission disabled", () => {
  const ui = app();
  ui.update(preview(), { "norman/previewImage": "old-thumbnail" });
  ui.update(preview({
    canSubmit: false,
    preview: { available: false, downloadUrl: "", error: "ELSTER validation failed" },
  }));
  assert.doesNotMatch(ui.elements.content.innerHTML, /old-thumbnail|Download PDF/);
  assert.match(ui.elements.content.innerHTML, /ELSTER validation failed/);
  ui.tabs[1].listeners.click();
  assert.match(ui.elements.content.innerHTML, /id="confirm"[^>]*disabled/);
  assert.match(ui.elements.content.innerHTML, /id="submit"[^>]*disabled/);
  assert.equal(ui.calls.filter(call => call.method === "tools/call").length, 0);
});
