const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");

// Exercise the shipped script with a controllable browser transport/clock.
// Synthetic files only; no network or Norman write is performed.
async function fixture() {
  const script = readFileSync(
    join(__dirname, "../norman_mcp/apps/document_upload.html"),
    "utf8",
  ).match(/<script>([\s\S]*?)<\/script>/)[1];
  function element(tag = "div") {
    return {
      tag,
      children: [],
      attrs: {},
      hidden: false,
      disabled: false,
      textContent: "",
      classList: { add() {}, remove() {} },
      append(...children) {
        this.children.push(...children);
      },
      replaceChildren(...children) {
        this.children = children;
      },
      setAttribute(name, value) {
        this.attrs[name] = value;
      },
      getBoundingClientRect() {
        return { height: 700 };
      },
      querySelectorAll() {
        return [];
      },
      focus() {},
    };
  }
  const elements = {};
  const timers = new Map();
  let now = 0,
    timerId = 0,
    fileId = 0;
  const requests = [],
    saved = [],
    messages = [];
  const state = { hangStatus: false, onSend: () => {} };
  const summary = () => ({
    files: saved,
    uploaded_count: saved.filter((f) => f.status === "uploaded").length,
  });
  const flush = async () => {
    for (let i = 0; i < 25; i++) await Promise.resolve();
  };
  const window = {
    parent: { postMessage() {} },
    addEventListener() {},
    openai: {
      toolOutput: {
        session_id: "synthetic-session",
        company_name: "Demo",
        country: "PL",
      },
      toolResponseMetadata: {
        upload: {
          ticket: "synthetic-ticket",
          base_url: "https://example.test",
          max_files: 20,
          max_file_size: 10000000,
          max_total_size: 100000000,
        },
      },
      callTool: async () => ({ structuredContent: summary() }),
      sendFollowUpMessage: async (message) => messages.push(message),
    },
  };
  class XHR {
    constructor() {
      this.upload = {};
      requests.push(this);
    }
    open() {
      assert.equal(
        typeof this.upload.onprogress,
        "function",
        "progress handler must precede open",
      );
    }
    setRequestHeader() {}
    send(form) {
      this.form = form;
      state.onSend(this);
    }
    abort() {
      this.aborted = true;
      this.onabort?.();
    }
    complete(result) {
      this.status = 200;
      this.responseText = JSON.stringify(result);
      this.onload();
    }
  }
  vm.runInNewContext(script, {
    window,
    parent: window.parent,
    document: {
      getElementById: (id) => (elements[id] ||= element()),
      createElement: element,
      querySelector: () => element(),
    },
    crypto: { randomUUID: () => `file-${++fileId}` },
    ResizeObserver: class {
      observe() {}
    },
    AbortController,
    setTimeout(fn, ms) {
      const id = ++timerId;
      timers.set(id, { fn, at: now + ms });
      return id;
    },
    clearTimeout: (id) => timers.delete(id),
    fetch: async (_url, options) => {
      if (state.hangStatus)
        return new Promise((_, reject) => {
          options.signal.addEventListener("abort", () =>
            reject(options.signal.reason),
          );
        });
      return { ok: true, json: async () => summary() };
    },
    XMLHttpRequest: XHR,
    FormData: class {
      constructor() {
        this.fields = {};
      }
      append(k, v) {
        this.fields[k] = v;
      }
    },
  });
  await flush();
  const descendants = (root) => [root, ...root.children.flatMap(descendants)];
  return {
    elements,
    requests,
    saved,
    state,
    messages,
    flush,
    retry: () =>
      descendants(elements.rows).find((e) =>
        e.attrs["aria-label"]?.startsWith("Retry upload"),
      ),
    text: () =>
      descendants(elements.rows)
        .map((e) => e.textContent)
        .join(" "),
    add(names = ["first.jpg", "second.jpg"]) {
      elements.picker.onchange({
        target: { files: names.map((name) => ({ name, size: 600000 })) },
      });
      for (const e of descendants(elements.rows)) {
        if (e.tag === "input" && e.value === "EXPENSE") e.onchange();
      }
    },
    async advance(ms) {
      const end = now + ms;
      while (true) {
        const next = [...timers]
          .filter(([, t]) => t.at <= end)
          .sort((a, b) => a[1].at - b[1].at)[0];
        if (!next) break;
        now = next[1].at;
        timers.delete(next[0]);
        next[1].fn();
        await flush();
      }
      now = end;
      await flush();
    },
    save(xhr, status = "uploaded") {
      const f = xhr.form.fields;
      const file = {
        id: f.file_id,
        file_name: f.file.name,
        cashflow_type: f.cashflow_type,
        status,
        ...(status === "uploaded" ? { attachment_id: `doc-${f.file_id}` } : {}),
      };
      saved.push(file);
      return file;
    },
  };
}

test("stalled first transfer releases the batch; explicit retry reuses its ID and skips saved files", async () => {
  const ui = await fixture();
  ui.state.onSend = (xhr) => {
    if (ui.requests.length > 1) xhr.complete(ui.save(xhr));
  };
  ui.add();
  const uploading = ui.elements.upload.onclick();
  await ui.advance(30000);
  await uploading;
  assert.equal(ui.requests[0].aborted, true);
  assert.equal(ui.requests.length, 2);
  assert.equal(ui.elements.total.textContent, "2 documents · 1 uploaded");
  assert.equal(ui.elements.check.disabled, false);
  assert.match(ui.text(), /Not received/);
  const original = ui.requests[0].form.fields;
  await ui.retry().onclick();
  assert.equal(ui.requests.length, 3);
  assert.equal(ui.requests[2].form.fields.file_id, original.file_id);
  assert.equal(ui.requests[2].form.fields.file, original.file);
  assert.equal(
    ui.requests[2].form.fields.cashflow_type,
    original.cashflow_type,
  );
  assert.equal(ui.elements.total.textContent, "2 documents · 2 uploaded");
  assert.equal(ui.retry(), undefined);
});

test("a lost success response is reconciled from server status without another POST", async () => {
  const ui = await fixture();
  ui.state.onSend = (xhr) => {
    ui.save(xhr);
  };
  ui.add(["receipt.jpg"]);
  const uploading = ui.elements.upload.onclick();
  await ui.advance(30000);
  await uploading;
  assert.equal(ui.elements.total.textContent, "1 documents · 1 uploaded");
  assert.equal(ui.retry(), undefined);
  assert.equal(ui.requests.length, 1);
});

test("an existing unconfirmed server reservation is never offered a retry", async () => {
  const ui = await fixture();
  ui.state.onSend = (xhr) => {
    ui.save(xhr, "unknown");
    xhr.onerror();
  };
  ui.add(["receipt.jpg"]);
  await ui.elements.upload.onclick();
  assert.equal(ui.retry(), undefined);
  assert.match(ui.text(), /Check status/);
  assert.equal(ui.requests.length, 1);
});

test("retry rechecks a late server success before sending anything", async () => {
  const ui = await fixture();
  ui.state.onSend = (xhr) => xhr.onerror();
  ui.add(["receipt.jpg"]);
  await ui.elements.upload.onclick();
  const retry = ui.retry();
  assert.ok(retry);
  ui.save(ui.requests[0]);
  await retry.onclick();
  assert.equal(ui.requests.length, 1);
  assert.equal(ui.elements.total.textContent, "1 documents · 1 uploaded");
});

test("progress resets the stall timer, and completed bytes may wait for a slow save", async () => {
  const ui = await fixture();
  ui.add(["receipt.jpg"]);
  const uploading = ui.elements.upload.onclick();
  await ui.advance(20000);
  ui.requests[0].upload.onprogress({
    lengthComputable: true,
    loaded: 10,
    total: 20,
  });
  await ui.advance(20000);
  assert.equal(ui.requests[0].aborted, undefined);
  ui.requests[0].upload.onload();
  await ui.advance(60000);
  assert.match(ui.text(), /Saving/);
  assert.equal(ui.requests[0].aborted, undefined);
  ui.requests[0].complete(ui.save(ui.requests[0]));
  await uploading;
});

test("a synchronous send failure and a hanging status check cannot strand Uploading", async () => {
  const ui = await fixture();
  ui.state.onSend = () => {
    throw Error("Unreadable file");
  };
  ui.state.hangStatus = true;
  ui.add(["receipt.jpg"]);
  const uploading = ui.elements.upload.onclick();
  await ui.flush();
  await ui.advance(10000);
  await uploading;
  assert.equal(ui.elements.upload.hidden, true);
  assert.equal(ui.elements.check.disabled, false);
  assert.match(ui.elements.notice.textContent, /timed out/);
  assert.equal(ui.retry(), undefined);
  ui.state.hangStatus = false;
  await ui.elements.check.onclick();
  assert.ok(ui.retry());
});
