const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { test, before, after } = require("node:test");
const { chromium } = require(process.env.NORMAN_PLAYWRIGHT || "playwright");
let browser;
before(async () => {
  browser = await chromium.launch({ headless: true });
});
after(async () => {
  await browser?.close();
});

async function fixture(
  width = 1100,
  { clock = false, pushOnInit = false, hold = [], settle = true } = {},
) {
  const page = await browser.newPage({ viewport: { width, height: 1000 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  if (clock) {
    await page.clock.install({ time: new Date("2026-09-30T10:00:00Z") });
    await page.clock.pauseAt(new Date("2026-09-30T10:00:01Z"));
  }
  await page.setContent(
    '<iframe title="Norman Inbox" style="border:0;width:100%;height:960px"></iframe>',
  );
  await page.evaluate(
    ({ pushOnInit, hold }) => {
    window.calls = [];
    window.mode = "";
    window.hooks = {};
    window.holdNames = hold;
    window.held = [];
    window.release = () => {
      for (const held of window.held.splice(0))
        held.target.postMessage(
          { jsonrpc: "2.0", id: held.id, result: held.result },
          "*",
        );
    };
    window.pushInbox = () =>
      document.querySelector("iframe").contentWindow.postMessage(
        {
          jsonrpc: "2.0",
          method: "ui/notifications/tool-result",
          params: { structuredContent: structuredClone(window.inbox) },
        },
        "*",
      );
    const companyId = "11111111-1111-4111-8111-111111111111";
    window.detail = {
      companyId,
      view: "approval",
      before: { vatRate: 7 },
      currentUnavailable: false,
      canApprove: true,
      execution: {
        publicId: "approval-1",
        ruleName: "Software VAT review",
        status: "awaiting_review",
        transaction: { description: "Adobe subscription" },
        actionsPlanned: [
          { type: "set_vat_rate", params: { vat_rate: 19 } },
          { type: "notify_in_app", params: { message: "Review complete" } },
        ],
      },
    };
    window.inbox = {
      companyId,
      view: "inbox",
      summary: { questions: 1, approvals: 51, taxReviewsShown: 0 },
      questions: [
        {
          publicId: "run-1",
          state: "active",
          blockedReason: "user_input",
          title: "Monthly close",
          blockedDetail: "What was this purchase for?",
          canChat: true,
        },
      ],
      runs: [],
      approvals: [
        {
          publicId: "approval-1",
          ruleName: "Software VAT review",
          transaction: { description: "Adobe subscription" },
        },
      ],
      taxReviews: [],
      unavailable: [],
      pagination: { page: 1, hasNext: true },
    };
    window.addEventListener("message", (e) => {
      if (e.source !== document.querySelector("iframe").contentWindow) return;
      const m = e.data;
      window.calls.push(m);
      if (m.method === "ui/notifications/initialized" && pushOnInit) {
        // Spec host: tool-input, then the result of the tool that opened
        // the View, right after initialization.
        e.source.postMessage(
          {
            jsonrpc: "2.0",
            method: "ui/notifications/tool-input",
            params: { arguments: {} },
          },
          "*",
        );
        e.source.postMessage(
          {
            jsonrpc: "2.0",
            method: "ui/notifications/tool-result",
            params: {
              structuredContent: {
                ...structuredClone(window.inbox),
                asOf: "2026-09-30T09:59:59+00:00",
              },
              content: [{ type: "text", text: "Norman Inbox" }],
            },
          },
          "*",
        );
      }
      // Answer requests only; the View's own replies carry no method.
      if (!m.id || !m.method) return;
      let result = {};
      if (m.method === "tools/call") {
        const { name, arguments: args } = m.params;
        if (name === "get_norman_inbox_data") {
          window.inbox.pagination.page = args.page;
          result = window.inbox;
        }
        if (name === "get_norman_approval_data")
          result = window.detailFailure
            ? { error: "Review temporarily unavailable." }
            : window.detail;
        if (name === "get_workflow_run") result = window.inbox.questions[0];
        if (name === "answer_workflow_question") {
          window.inbox.questions = [];
          window.inbox.summary.questions = 0;
        }
        if (name === "approve_rule_execution") {
          if (window.mode === "failure")
            result = { error: "Approval failed; nothing confirmed." };
          else {
            window.detail.canApprove = false;
            window.detail.execution.status = "success";
            window.detail.execution.actionsResult = [
              { type: "set_vat_rate", status: "success" },
            ];
            window.inbox.approvals = [];
            window.inbox.summary.approvals = 50;
          }
        }
        if (name === "dismiss_rule_execution") {
          window.detail.canApprove = false;
          window.detail.execution.status = "dismissed";
        }
        if (window.hooks[name]) result = window.hooks[name](args);
        result = { structuredContent: structuredClone(result), content: [] };
        if (window.holdNames.includes(name)) {
          window.held.push({ target: e.source, id: m.id, result });
          return;
        }
      }
      e.source.postMessage({ jsonrpc: "2.0", id: m.id, result }, "*");
    });
    },
    { pushOnInit, hold },
  );
  const html = readFileSync(
    join(__dirname, "../norman_mcp/apps/inbox.html"),
    "utf8",
  ).replace("const state = {", "const state = window.__inboxTestState = {");
  await page
    .locator("iframe")
    .evaluate((frame, html) => (frame.srcdoc = html), html);
  const ui = page.frameLocator("iframe");
  await ui.getByRole("button", { name: "Review changes" }).waitFor();
  if (settle) await idle(page);
  return { page, ui, errors };
}
async function until(page, predicate, arg, what = "condition") {
  // Node-side polling: works while the browser clock is paused.
  const deadline = Date.now() + 3000;
  while (Date.now() < deadline) {
    await flush(page);
    if (await page.frames()[1].evaluate(predicate, arg)) return;
  }
  assert.fail(`Timed out waiting for ${what}`);
}
async function setShown(page, shown) {
  await page
    .locator("iframe")
    .evaluate((frame, shown) => (frame.style.display = shown ? "" : "none"), shown);
  await until(
    page,
    (shown) => window.__inboxTestState.visible === shown,
    shown,
    shown ? "visible" : "hidden",
  );
}
async function view(page) {
  return page.frames()[1].evaluate(() => ({
    status: document.querySelector("#status").textContent,
    confirm: document.querySelector("#confirm")?.checked ?? null,
    approve: document.querySelector("#approve")?.disabled ?? null,
    tag: document.querySelector("aside .tag")?.textContent ?? null,
  }));
}
async function idle(page) {
  // Rendering precedes context RPC completion. Observe the test-exposed state
  // so advancing fake time cannot run an RPC timeout before polling is armed.
  // Node's clock remains real; browser waitForFunction retries can freeze along
  // with RAF when page.clock.pauseAt is active.
  const deadline = Date.now() + 3000;
  while (Date.now() < deadline) {
    await flush(page);
    if (
      await page.frames()[1].evaluate(() => {
        const state = window.__inboxTestState;
        return (
          state.initialized &&
          state.visible &&
          state.intersecting &&
          !state.busy &&
          !state.refreshPromise &&
          state.pending.size === 0 &&
          state.pollTimer !== null
        );
      })
    )
      return;
  }
  assert.fail(
    `Inbox did not become idle: ${JSON.stringify(
      await page.frames()[1].evaluate(() => {
        const state = window.__inboxTestState;
        return {
          initialized: state.initialized,
          busy: state.busy,
          refresh: !!state.refreshPromise,
          pending: [...state.pending.keys()],
          pollTimer: state.pollTimer,
          visible: state.visible,
          intersecting: state.intersecting,
          wanted: state.refreshWanted,
          status: document.querySelector("#status").textContent,
        };
      }),
    )}`,
  );
}
async function toolCalls(page, name) {
  return page.evaluate(
    (name) => window.calls.filter((call) => call.params?.name === name),
    name,
  );
}
async function flush(page) {
  // Flush browser message tasks without advancing the polling clock.
  for (let i = 0; i < 3; i++)
    await page.evaluate(
      () =>
        new Promise((resolve) => {
          const channel = new MessageChannel();
          channel.port1.onmessage = () => {
            channel.port1.close();
            channel.port2.close();
            resolve();
          };
          channel.port2.postMessage(null);
        }),
    );
}
async function settled(page) {
  // Real-time wait for tests without a fake clock: the action finished.
  await page
    .frames()[1]
    .waitForFunction(
      () =>
        !window.__inboxTestState.busy &&
        window.__inboxTestState.pending.size === 0,
    );
  return page
    .frames()[1]
    .evaluate(() => document.querySelector("#status").textContent);
}
async function mutations(page) {
  return page.evaluate(() =>
    window.calls.filter(
      (c) =>
        c.method === "tools/call" &&
        [
          "approve_rule_execution",
          "dismiss_rule_execution",
          "undo_rule_execution",
          "answer_workflow_question",
        ].includes(c.params.name),
    ),
  );
}
// A host with only the window.openai bridge: it never answers postMessage
// JSON-RPC, so ui/initialize stays unanswered.
async function bridgeless(width = 1100) {
  const page = await browser.newPage({ viewport: { width, height: 1000 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.clock.install({ time: new Date("2026-09-30T10:00:00Z") });
  await page.clock.pauseAt(new Date("2026-09-30T10:00:01Z"));
  await page.setContent(
    '<iframe title="Norman Inbox" style="border:0;width:100%;height:960px"></iframe>',
  );
  await page.evaluate(() => {
    window.calls = [];
    window.addEventListener("message", (e) => window.calls.push(e.data));
  });
  const inbox = {
    companyId: "11111111-1111-4111-8111-111111111111",
    view: "inbox",
    summary: { questions: 0, approvals: 3, taxReviewsShown: 0 },
    questions: [],
    runs: [],
    approvals: [],
    taxReviews: [],
    unavailable: [],
    pagination: { page: 1, hasNext: false },
  };
  const shim = `<script>window.openaiCalls = []; window.openai = { toolOutput: ${JSON.stringify(
    inbox,
  )}, callTool: async (name, args) => { window.openaiCalls.push({ name, args }); return { structuredContent: ${JSON.stringify(
    inbox,
  )} }; }, setWidgetState() {} };</script>`;
  const html = readFileSync(
    join(__dirname, "../norman_mcp/apps/inbox.html"),
    "utf8",
  )
    .replace("<head>", `<head>${shim}`)
    .replace("const state = {", "const state = window.__inboxTestState = {");
  await page
    .locator("iframe")
    .evaluate((frame, html) => (frame.srcdoc = html), html);
  await page.frameLocator("iframe").locator("#content").waitFor();
  return { page, ui: page.frameLocator("iframe"), errors };
}

test("approval requires consent, shows every action, executes once and reads actual result", async () => {
  const { page, ui, errors } = await fixture();
  try {
    await ui.getByRole("button", { name: "Review changes" }).click();
    await ui.getByRole("button", { name: "Approve execution" }).waitFor();
    assert.equal(
      await ui.getByRole("button", { name: "Approve execution" }).isDisabled(),
      true,
    );
    assert.equal((await mutations(page)).length, 0);
    assert.equal(
      await ui
        .getByText("Send an in-app notification", { exact: true })
        .count(),
      1,
    );
    await ui.locator("#confirm").check();
    await ui.getByRole("button", { name: "Approve execution" }).click();
    await ui.getByText("Actual result", { exact: true }).waitFor();
    assert.equal((await mutations(page)).length, 1);
    assert.equal(
      (await mutations(page))[0].params.name,
      "approve_rule_execution",
    );
    assert.equal(await ui.locator("#confirm").count(), 0);
    assert.deepEqual(errors, []);
    if (process.env.NORMAN_UI_SCREENSHOT)
      await page.screenshot({
        path: process.env.NORMAN_UI_SCREENSHOT,
        fullPage: true,
      });
  } finally {
    await page.close();
  }
});

test("a changed review clears consent and never runs a stale approval", async () => {
  const { page, ui, errors } = await fixture();
  try {
    await ui.getByRole("button", { name: "Review changes" }).click();
    await ui.locator("#confirm").check();
    await page.evaluate(() => (window.detail.before.vatRate = 0));
    await ui.getByRole("button", { name: "Approve execution" }).click();
    await ui
      .getByText(
        "This approval changed. Review the current values and confirm again.",
      )
      .waitFor();
    assert.equal((await mutations(page)).length, 0);
    assert.equal(await ui.locator("#confirm").isChecked(), false);
    assert.equal(
      await ui.getByRole("button", { name: "Approve execution" }).isDisabled(),
      true,
    );
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
});

test("mobile Inbox paginates, escapes source content and submits a workflow answer", async () => {
  const { page, ui, errors } = await fixture(390);
  try {
    await page.evaluate(
      () =>
        (window.inbox.questions[0].title =
          '<img src=x onerror="window.compromised=true">'),
    );
    await ui.getByRole("button", { name: "Refresh", exact: true }).click();
    await ui
      .getByText('<img src=x onerror="window.compromised=true">', {
        exact: true,
      })
      .waitFor();
    assert.equal(await ui.locator("img").count(), 0);
    await ui.getByRole("button", { name: "More approvals" }).click();
    await ui.getByRole("button", { name: "Previous approvals" }).waitFor();
    assert.equal(
      await page.evaluate(
        () =>
          window.calls
            .filter((c) => c.params?.name === "get_norman_inbox_data")
            .at(-1).params.arguments.page,
      ),
      2,
    );
    await ui.getByRole("button", { name: "Review question" }).click();
    await ui.locator("#answer").fill("Annual software license");
    await ui.getByRole("button", { name: "Send answer to Norman" }).click();
    await ui.getByText("Review a decision", { exact: true }).waitFor();
    assert.equal(
      (await mutations(page))[0].params.arguments.answer,
      "Annual software license",
    );
    assert.equal(
      await page
        .frames()[1]
        .evaluate(() => document.documentElement.scrollWidth <= innerWidth),
      true,
    );
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
});

test("failed approval stays unconfirmed; missing current values cannot be approved", async () => {
  const { page, ui, errors } = await fixture();
  try {
    await ui.getByRole("button", { name: "Review changes" }).click();
    await ui.locator("#confirm").check();
    await page.evaluate(() => (window.mode = "failure"));
    await ui.getByRole("button", { name: "Approve execution" }).click();
    await ui.getByText("Approval failed; nothing confirmed.").waitFor();
    assert.equal(
      await ui.getByText("Actual result", { exact: true }).count(),
      0,
    );
    await page.evaluate(() => (window.detail.currentUnavailable = true));
    await ui.getByRole("button", { name: "Review changes" }).click();
    await ui
      .getByText(
        "Current transaction values are unavailable. Discuss this in chat before deciding.",
      )
      .waitFor();
    assert.equal(await ui.locator("#approve").count(), 0);
    assert.equal(
      await ui.getByRole("button", { name: "Dismiss", exact: true }).count(),
      1,
    );
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
});

test("visible Inbox refreshes without writes or repeated unchanged model context", async () => {
  const { page, ui, errors } = await fixture(1100, { clock: true });
  try {
    const count = (name) => toolCalls(page, name);
    assert.equal((await count("get_norman_inbox_data")).length, 1);
    await page.evaluate(() => (window.inbox.summary.approvals = 52));
    await page.clock.runFor(30_001);
    await ui
      .locator(".metric strong")
      .nth(1)
      .getByText("52", { exact: true })
      .waitFor();
    await idle(page);
    const contexts = await page.evaluate(
      () =>
        window.calls.filter((call) => call.method === "ui/update-model-context")
          .length,
    );
    // Unchanged checks back off: the next two come 30 s and 60 s apart.
    for (const wait of [30_001, 60_001]) {
      await page.clock.runFor(wait);
      await idle(page);
    }
    assert.equal((await count("get_norman_inbox_data")).length, 4);
    assert.equal(
      await page.evaluate(
        () =>
          window.calls.filter(
            (call) => call.method === "ui/update-model-context",
          ).length,
      ),
      contexts,
    );
    assert.equal(
      await page.evaluate(() =>
        window.calls.some((call) => call.method === "ui/message"),
      ),
      false,
    );
    assert.equal((await mutations(page)).length, 0);
    assert.match(
      await ui.locator("#freshness").innerText(),
      /Checked .*Auto refresh every 30s/,
    );
    assert.equal(
      await page
        .frames()[1]
        .evaluate(() =>
          [...document.querySelectorAll("button,.card,.metric,.detail")].every(
            (element) =>
              getComputedStyle(element).borderTopLeftRadius === "0px" &&
              getComputedStyle(element).boxShadow === "none",
          ),
        ),
      true,
    );
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
});

test("poll keeps page, selected review and consent only for an unchanged review", async () => {
  const { page, ui, errors } = await fixture(1100, { clock: true });
  try {
    await ui.getByRole("button", { name: "More approvals" }).click();
    await idle(page);
    await ui.getByRole("button", { name: "Review changes" }).click();
    await idle(page);
    await ui.locator("#confirm").check();
    await page.clock.runFor(1);
    await idle(page);
    await page.evaluate(() => {
      window.inbox.summary.approvals = 52;
      window.detail.execution.updatedAt = "2026-09-30T10:01:00Z";
    });
    await page.clock.runFor(30_001);
    await ui
      .locator(".metric strong")
      .nth(1)
      .getByText("52", { exact: true })
      .waitFor();
    await idle(page);
    assert.equal(
      (await toolCalls(page, "get_norman_inbox_data")).at(-1).params.arguments
        .page,
      2,
    );
    assert.equal(
      await ui.locator("aside h2").innerText(),
      "Software VAT review",
    );
    assert.equal(await ui.locator("#confirm").isChecked(), true);
    assert.equal(await ui.locator("#approve").isEnabled(), true);
    await page.evaluate(() => (window.detail.before.vatRate = 0));
    await page.clock.runFor(30_001);
    await ui
      .getByText(
        "This approval changed. Review the current values and confirm again.",
      )
      .waitFor();
    await idle(page);
    assert.equal(await ui.locator("#confirm").isChecked(), false);
    assert.equal(await ui.locator("#approve").isDisabled(), true);
    assert.equal((await mutations(page)).length, 0);
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
});

test("poll preserves workflow draft and typing focus while refreshing its question", async () => {
  const { page, ui, errors } = await fixture(390, { clock: true });
  try {
    await ui.getByRole("button", { name: "Review question" }).click();
    await idle(page);
    await ui.locator("#answer").fill("Annual software license, not sent yet");
    await page.clock.runFor(1);
    await idle(page);
    await ui
      .locator("#answer")
      .evaluate((input) => input.setSelectionRange(6, 14));
    await page.evaluate(() => {
      window.inbox.summary.approvals = 53;
      window.inbox.questions[0].blockedDetail =
        "What was the Adobe purchase for?";
    });
    await page.clock.runFor(30_001);
    await ui
      .locator("aside")
      .getByText("What was the Adobe purchase for?", { exact: true })
      .waitFor();
    await idle(page);
    assert.equal(
      await ui.locator("#answer").inputValue(),
      "Annual software license, not sent yet",
    );
    assert.deepEqual(
      await ui
        .locator("#answer")
        .evaluate((input) => [
          document.activeElement === input,
          input.selectionStart,
          input.selectionEnd,
        ]),
      [true, 6, 14],
    );
    assert.equal((await mutations(page)).length, 0);
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
});

test("hidden iframe pauses polling and visibility/focus resume with a fresh read", async () => {
  const { page, ui, errors } = await fixture(1100, { clock: true });
  try {
    await page
      .locator("iframe")
      .evaluate((frame) => (frame.style.display = "none"));
    await ui
      .locator("#freshness")
      .getByText(/Auto refresh paused/)
      .waitFor({ state: "attached" });
    const before = (await toolCalls(page, "get_norman_inbox_data")).length;
    await page.clock.runFor(90_001);
    await flush(page);
    assert.equal(
      (await toolCalls(page, "get_norman_inbox_data")).length,
      before,
    );
    await page.evaluate(() => (window.inbox.summary.approvals = 54));
    await page
      .locator("iframe")
      .evaluate((frame) => (frame.style.display = ""));
    // IntersectionObserver uses browser rendering, not the virtual timer clock.
    // Wait for visibility to arm the immediate read before advancing that clock.
    await idle(page);
    assert.equal(
      (await toolCalls(page, "get_norman_inbox_data")).length,
      before,
    );
    await page.clock.runFor(1);
    await idle(page);
    await ui
      .locator(".metric strong")
      .nth(1)
      .getByText("54", { exact: true })
      .waitFor();
    await idle(page);
    const resumed = (await toolCalls(page, "get_norman_inbox_data")).length;
    // Focus re-reads only data older than half the poll interval.
    for (const [wait, reads] of [
      [0, resumed],
      [15_000, resumed + 1],
    ]) {
      await page.clock.runFor(wait);
      await page
        .frames()[1]
        .evaluate(() => window.dispatchEvent(new Event("focus")));
      await page.clock.runFor(1);
      await idle(page);
      assert.equal(
        (await toolCalls(page, "get_norman_inbox_data")).length,
        reads,
      );
    }
    assert.equal((await mutations(page)).length, 0);
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
});

test("polls never overlap and next interval starts after the read completes", async () => {
  const { page, ui, errors } = await fixture(1100, { clock: true });
  try {
    await page.evaluate(() => (window.holdNames = ["get_norman_inbox_data"]));
    await page.clock.runFor(30_001);
    await flush(page);
    assert.equal(await page.evaluate(() => window.held.length), 1);
    await page.clock.runFor(20_000);
    await flush(page);
    assert.equal((await toolCalls(page, "get_norman_inbox_data")).length, 2);
    await page.evaluate(() => {
      window.holdNames = [];
      window.inbox.summary.approvals = 55;
      window.release();
    });
    await idle(page);
    // The held read returned unchanged data, so the next check backs off to
    // 60 s, counted from when that read completed.
    await page.clock.runFor(59_999);
    assert.equal((await toolCalls(page, "get_norman_inbox_data")).length, 2);
    await page.clock.runFor(2);
    await ui
      .locator(".metric strong")
      .nth(1)
      .getByText("55", { exact: true })
      .waitFor();
    assert.equal((await toolCalls(page, "get_norman_inbox_data")).length, 3);
    assert.equal((await mutations(page)).length, 0);
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
});

test("company notification rejects older pending reads and clears the previous review", async () => {
  const { page, ui, errors } = await fixture(1100, { clock: true });
  try {
    await ui.getByRole("button", { name: "Review changes" }).click();
    await idle(page);
    await ui.locator("#confirm").check();
    await page.clock.runFor(1);
    await idle(page);
    await page.evaluate(() => (window.holdNames = ["get_norman_inbox_data"]));
    await page.clock.runFor(30_001);
    await flush(page);
    await page.evaluate(() => {
      window.inbox.companyId = "22222222-2222-4222-8222-222222222222";
      window.inbox.summary.approvals = 56;
      window.inbox.approvals = [];
      window.inbox.questions = [];
      window.inbox.summary.questions = 0;
      window.pushInbox();
    });
    await ui.getByText("Review a decision", { exact: true }).waitFor();
    assert.equal(await ui.locator("#confirm").count(), 0);
    await page.evaluate(() => {
      window.holdNames = [];
      window.release();
    });
    await flush(page);
    await page.clock.runFor(1);
    await flush(page);
    assert.equal(await ui.locator(".metric strong").nth(1).innerText(), "56");
    assert.equal(
      await ui.getByText("Adobe subscription", { exact: true }).count(),
      0,
    );
    assert.equal((await mutations(page)).length, 0);
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
});

test("company change during approval preflight prevents the mutation and late detail", async () => {
  const { page, ui, errors } = await fixture(1100, { clock: true });
  try {
    await ui.getByRole("button", { name: "Review changes" }).click();
    await idle(page);
    await ui.locator("#confirm").check();
    await page.clock.runFor(1);
    await idle(page);
    await page.evaluate(
      () => (window.holdNames = ["get_norman_approval_data"]),
    );
    await ui.getByRole("button", { name: "Approve execution" }).click();
    await flush(page);
    assert.equal(await page.evaluate(() => window.held.length), 1);
    await page.evaluate(() => {
      window.inbox.companyId = "22222222-2222-4222-8222-222222222222";
      window.inbox.approvals = [];
      window.inbox.questions = [];
      window.pushInbox();
    });
    await ui.getByText("Review a decision", { exact: true }).waitFor();
    await page.evaluate(() => {
      window.holdNames = [];
      window.release();
    });
    await flush(page);
    await page.clock.runFor(1);
    await flush(page);
    assert.equal((await mutations(page)).length, 0);
    assert.equal(await ui.locator("#confirm").count(), 0);
    assert.equal(
      await ui.getByText("Adobe subscription", { exact: true }).count(),
      0,
    );
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
});

test("unavailable live approval keeps the selection but cannot preserve consent", async () => {
  const { page, ui, errors } = await fixture(1100, { clock: true });
  try {
    await ui.getByRole("button", { name: "Review changes" }).click();
    await idle(page);
    await ui.locator("#confirm").check();
    await page.clock.runFor(1);
    await idle(page);
    await page.evaluate(() => (window.detailFailure = true));
    await page.clock.runFor(30_001);
    await ui
      .getByText("Latest review unavailable. Refresh before confirming.")
      .waitFor();
    await idle(page);
    assert.equal(
      await ui.locator("aside h2").innerText(),
      "Software VAT review",
    );
    assert.equal(await ui.locator("#confirm").isChecked(), false);
    assert.equal(await ui.locator("#confirm").isDisabled(), true);
    assert.equal(await ui.locator("#approve").isDisabled(), true);
    await page.evaluate(() => (window.detailFailure = false));
    await page.clock.runFor(30_001);
    await idle(page);
    assert.equal(await ui.locator("#confirm").isEnabled(), true);
    assert.equal(await ui.locator("#confirm").isChecked(), false);
    assert.equal((await mutations(page)).length, 0);
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
});

test("host requests are answered and never consume a pending response id", async () => {
  const { page, ui, errors } = await fixture(1100, { clock: true });
  try {
    await page.evaluate(() => (window.holdNames = ["get_norman_inbox_data"]));
    await page.clock.runFor(30_001);
    await flush(page);
    const view = page.frames()[1];
    const id = await view.evaluate(
      () => [...window.__inboxTestState.pending.keys()][0],
    );
    const send = (id, method) =>
      page.evaluate(
        ({ id, method }) =>
          document
            .querySelector("iframe")
            .contentWindow.postMessage(
              { jsonrpc: "2.0", id, method, params: {} },
              "*",
            ),
        { id, method },
      );
    const replies = (id) =>
      page.evaluate(
        (id) =>
          window.calls.filter((c) => c.id === id && c.method === undefined),
        id,
      );
    // Host ids are independent of the View's: a host request that reuses
    // the id of a pending poll is a request, not that poll's response.
    await send(id, "ping");
    await flush(page);
    assert.deepEqual(await replies(id), [{ jsonrpc: "2.0", id, result: {} }]);
    assert.equal(
      await view.evaluate(
        (id) => window.__inboxTestState.pending.has(id),
        id,
      ),
      true,
    );
    await send(777, "ui/unknown-request");
    await flush(page);
    assert.equal((await replies(777))[0].error.code, -32601);
    await send(id, "ui/resource-teardown");
    await flush(page);
    assert.equal((await replies(id)).length, 2);
    assert.equal(
      await view.evaluate(() => window.__inboxTestState.disposed),
      true,
    );
    await page.evaluate(() => {
      window.holdNames = [];
      window.release();
    });
    await flush(page);
    assert.doesNotMatch(
      await ui.locator("#status").innerText(),
      /Could not refresh/,
    );
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
});

test("host without ui/initialize renders window.openai tool output and polls through it", async () => {
  const { page, errors } = await bridgeless();
  try {
    const view = page.frames()[1];
    const shown = () =>
      view.evaluate(() => ({
        approvals: document.querySelectorAll(".metric strong")[1]?.textContent,
        content: document.querySelector("#content").innerText,
      }));
    await flush(page);
    await page.clock.runFor(1_000);
    await flush(page);
    assert.equal((await shown()).approvals, "3");
    assert.doesNotMatch((await shown()).content, /Connecting to Norman/);
    // ui/initialize is abandoned after 5 s, then polling runs through
    // window.openai.callTool.
    await page.clock.runFor(4_001);
    await flush(page);
    assert.deepEqual(
      await view.evaluate(() => {
        const state = window.__inboxTestState;
        return [state.initialized, state.ready, state.pollTimer !== null];
      }),
      [true, false, true],
    );
    await page.clock.runFor(30_001);
    await flush(page);
    assert.deepEqual(
      await view.evaluate(() => window.openaiCalls.map((call) => call.name)),
      ["get_norman_inbox_data"],
    );
    assert.deepEqual(
      await page.evaluate(() => window.calls.map((call) => call.method)),
      ["ui/initialize"],
    );
    // A host that answers ui/initialize late still completes the handshake.
    await page.evaluate(() =>
      document.querySelector("iframe").contentWindow.postMessage(
        {
          jsonrpc: "2.0",
          id: window.calls.find((call) => call.method === "ui/initialize").id,
          result: {},
        },
        "*",
      ),
    );
    await flush(page);
    assert.deepEqual(
      await page.evaluate(() => window.calls.map((call) => call.method)),
      [
        "ui/initialize",
        "ui/notifications/initialized",
        "ui/update-model-context",
      ],
    );
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
});

test("model context carries the summary and the selected review in every update", async () => {
  const { page, ui, errors } = await fixture(1100, { clock: true });
  try {
    const contexts = () =>
      page.evaluate(() =>
        window.calls
          .filter((call) => call.method === "ui/update-model-context")
          .map((call) => call.params.structuredContent),
      );
    // The host keeps only the last update (ext-apps overwrite semantics).
    const kept = async () => {
      const last = (await contexts()).at(-1);
      return [last.view, last.summary?.approvals, last.selected?.execution?.publicId];
    };
    await ui.getByRole("button", { name: "Review changes" }).click();
    await idle(page);
    await page.clock.runFor(1);
    await idle(page);
    assert.deepEqual(await kept(), ["inbox", 51, "approval-1"]);
    await page.evaluate(() => (window.inbox.summary.approvals = 52));
    await page.clock.runFor(30_001);
    await ui
      .locator(".metric strong")
      .nth(1)
      .getByText("52", { exact: true })
      .waitFor();
    await idle(page);
    assert.deepEqual(await kept(), ["inbox", 52, "approval-1"]);
    const sent = (await contexts()).length;
    await page.clock.runFor(30_001);
    await idle(page);
    assert.equal((await contexts()).length, sent);
    assert.equal(await ui.locator("aside h2").innerText(), "Software VAT review");
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
});

async function consented(page, ui) {
  await ui.getByRole("button", { name: "Review changes" }).click();
  await idle(page);
  await page.clock.runFor(1);
  await idle(page);
  await ui.locator("#confirm").check();
  await page.clock.runFor(1);
  await idle(page);
}
const quiet = () =>
  !window.__inboxTestState.busy && window.__inboxTestState.pending.size === 0;

test("a pre-approval read discarded while hidden clears consent and approves nothing", async () => {
  const { page, ui, errors } = await fixture(1100, { clock: true });
  try {
    await consented(page, ui);
    await page.evaluate(
      () => (window.holdNames = ["get_norman_approval_data"]),
    );
    await ui.getByRole("button", { name: "Approve execution" }).click();
    await flush(page);
    assert.equal(await page.evaluate(() => window.held.length), 1);
    await setShown(page, false);
    await page.evaluate(() => {
      window.holdNames = [];
      window.release();
    });
    await until(page, quiet, undefined, "the approval to settle");
    assert.deepEqual(await view(page), {
      status:
        "Nothing was approved. Review the current values and confirm again.",
      confirm: false,
      approve: true,
      tag: "Awaiting your review",
    });
    await setShown(page, true);
    await page.clock.runFor(1);
    await idle(page);
    assert.equal((await view(page)).confirm, false);
    assert.equal((await mutations(page)).length, 0);
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
});

test("an approval sent before the frame was hidden reports Norman's actual result", async () => {
  const { page, ui, errors } = await fixture(1100, { clock: true });
  try {
    await consented(page, ui);
    await page.evaluate(() => (window.holdNames = ["approve_rule_execution"]));
    await ui.getByRole("button", { name: "Approve execution" }).click();
    // The preflight read answers at once; wait until the approval is held.
    for (let i = 0; i < 20; i++) {
      if (await page.evaluate(() => window.held.length)) break;
      await flush(page);
    }
    assert.equal(await page.evaluate(() => window.held.length), 1);
    await setShown(page, false);
    await page.evaluate(() => {
      window.holdNames = [];
      window.release();
    });
    await until(page, quiet, undefined, "the approval report");
    assert.deepEqual(await view(page), {
      status: "Approval sent. Norman now reports: Completed.",
      confirm: null,
      approve: null,
      tag: "Completed",
    });
    assert.equal(
      await page
        .frames()[1]
        .evaluate(() => document.querySelector("aside").innerText.includes("Actual result")),
      true,
    );
    assert.deepEqual(
      (await mutations(page)).map((call) => call.params.name),
      ["approve_rule_execution"],
    );
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
});

test("startup on a host that pushes the tool result ends in a normal status", async () => {
  const { page, ui, errors } = await fixture(1100, {
    clock: true,
    pushOnInit: true,
    hold: ["get_norman_inbox_data"],
    settle: false,
  });
  try {
    // The pushed result is on screen while our own first read is in flight.
    assert.equal((await view(page)).status, "Working…");
    await page.evaluate(() => {
      window.holdNames = [];
      window.release();
    });
    await idle(page);
    assert.equal((await view(page)).status, "Updated from Norman.");
    await page.clock.runFor(1);
    await idle(page);
    assert.equal((await view(page)).status, "Updated from Norman.");
    // The push does not cost an extra read or schedule an immediate one.
    assert.equal((await toolCalls(page, "get_norman_inbox_data")).length, 1);
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
});

test("idle polling backs off to five minutes and resets on change or interaction", async () => {
  const { page, ui, errors } = await fixture(1100, { clock: true });
  try {
    const reads = async () =>
      (await toolCalls(page, "get_norman_inbox_data")).length;
    const check = async (wait, expected) => {
      await page.clock.runFor(wait);
      await idle(page);
      assert.equal(await reads(), expected, `after ${wait} ms`);
    };
    // Unchanged checks come 30 s, 60 s, 120 s, then 300 s apart.
    await check(30_001, 2);
    for (const [gap, expected] of [
      [60_000, 3],
      [120_000, 4],
      [300_000, 5],
      [300_000, 6],
    ]) {
      await check(gap - 1, expected - 1);
      await check(2, expected);
    }
    // A check that finds a change returns to 30 s.
    await page.evaluate(() => (window.inbox.summary.approvals = 60));
    await check(300_001, 7);
    await check(30_001, 8);
    // Unchanged again (next in 60 s); interaction brings it back to 30 s.
    await ui.locator("h1").click();
    await check(30_001, 9);
    assert.equal((await mutations(page)).length, 0);
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
});

test("focus and visibility re-read only data older than half the interval", async () => {
  const { page, errors } = await fixture(1100, { clock: true });
  try {
    const reads = async () =>
      (await toolCalls(page, "get_norman_inbox_data")).length;
    const focus = async () => {
      await page
        .frames()[1]
        .evaluate(() => window.dispatchEvent(new Event("focus")));
      await page.clock.runFor(1);
      await idle(page);
    };
    await focus();
    assert.equal(await reads(), 1);
    await setShown(page, false);
    await setShown(page, true);
    await page.clock.runFor(1);
    await idle(page);
    assert.equal(await reads(), 1);
    await page.clock.runFor(15_000);
    await focus();
    assert.equal(await reads(), 2);
    // The wake-up read restarts the interval.
    await page.clock.runFor(29_998);
    await idle(page);
    assert.equal(await reads(), 2);
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
});

test("host-pushed results never trigger an immediate re-read loop", async () => {
  const { page, ui, errors } = await fixture(1100, { clock: true });
  try {
    const reads = async () =>
      (await toolCalls(page, "get_norman_inbox_data")).length;
    // A pushed change is shown and counts as a check.
    await page.evaluate(() => {
      window.inbox.summary.approvals = 57;
      window.pushInbox();
    });
    await ui
      .locator(".metric strong")
      .nth(1)
      .getByText("57", { exact: true })
      .waitFor();
    await page.clock.runFor(1);
    await idle(page);
    assert.equal(await reads(), 1);
    // A host that echoes every read as a tool-result while a running
    // workflow changes updatedAt on each read.
    await page.evaluate(() => {
      let n = 0;
      window.inbox.runs = [
        {
          publicId: "run-2",
          state: "active",
          title: "Month-end close",
          isRunning: true,
          updatedAt: "t0",
          steps: [],
        },
      ];
      window.hooks.get_norman_inbox_data = () => {
        window.inbox.runs[0].updatedAt = `t${++n}`;
        window.pushInbox();
        return window.inbox;
      };
    });
    await page.clock.runFor(30_001);
    for (let i = 0; i < 40; i++) {
      await page.clock.runFor(25);
      await flush(page);
    }
    await idle(page);
    assert.equal(await reads(), 2);
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
});

const QUESTION_B =
  "Should transaction 2026-09-12 (EUR 4,800) be booked as private?";
const DRAFT = "It was the annual Adobe licence";
async function drafted(page, ui) {
  await ui.getByRole("button", { name: "Review question" }).click();
  await idle(page);
  await page.clock.runFor(1);
  await idle(page);
  await ui.locator("#answer").fill(DRAFT);
}
const sentAnswers = async (page) =>
  (await mutations(page)).map((call) => call.params.arguments.answer);

test("a poll that changes the question keeps the draft bound to the old one", async () => {
  const { page, ui, errors } = await fixture(1100, { clock: true });
  try {
    await drafted(page, ui);
    // Answered elsewhere; the same run now asks something else.
    await page.evaluate(
      (question) => (window.inbox.questions[0].blockedDetail = question),
      QUESTION_B,
    );
    await page.clock.runFor(30_001);
    await ui.locator("aside").getByText(QUESTION_B, { exact: true }).waitFor();
    await idle(page);
    assert.equal(
      await ui.locator("#status").innerText(),
      "This workflow question changed. Review your answer before sending.",
    );
    assert.match(
      await ui.locator("aside p.error").innerText(),
      /You wrote it for: “What was this purchase for\?”/,
    );
    assert.equal(await ui.locator("#answer").inputValue(), DRAFT);
    assert.equal(await ui.locator("#answer-send").isDisabled(), true);
    // Even a direct send is checked against the draft's own question.
    await page
      .frames()[1]
      .evaluate(() => document.querySelector("#answer-send").onclick());
    await idle(page);
    assert.deepEqual(await sentAnswers(page), []);
    // Confirming binds the draft to the question now shown.
    await ui
      .getByRole("button", { name: "Use my answer for this question" })
      .click();
    assert.equal(await ui.locator("aside p.error").count(), 0);
    await ui.getByRole("button", { name: "Send answer to Norman" }).click();
    await idle(page);
    assert.deepEqual(await sentAnswers(page), [DRAFT]);
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
});

test("sending re-reads the question and blocks a draft written for another one", async () => {
  const { page, ui, errors } = await fixture(1100, { clock: true });
  try {
    await drafted(page, ui);
    await page.evaluate(
      (question) => (window.inbox.questions[0].blockedDetail = question),
      QUESTION_B,
    );
    await ui.getByRole("button", { name: "Send answer to Norman" }).click();
    await ui.locator("aside").getByText(QUESTION_B, { exact: true }).waitFor();
    await idle(page);
    assert.equal(
      await ui.locator("#status").innerText(),
      "This workflow question changed. Review your answer before sending.",
    );
    assert.equal(await ui.locator("aside p.error").count(), 1);
    assert.equal(await ui.locator("#answer").inputValue(), DRAFT);
    assert.equal(await ui.locator("#answer-send").isDisabled(), true);
    // Clearing the draft releases it; a new draft belongs to the new question.
    await ui.locator("#answer").fill("");
    assert.equal(await ui.locator("aside p.error").count(), 0);
    await ui.locator("#answer").fill("No, it is a business expense");
    await ui.getByRole("button", { name: "Send answer to Norman" }).click();
    await idle(page);
    assert.deepEqual(await sentAnswers(page), ["No, it is a business expense"]);
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
});

test("only the person who started a workflow gets an answer box", async () => {
  const { page, ui, errors } = await fixture();
  try {
    const note = "Only the person who started this workflow can answer it here.";
    const aside = ui.locator("aside");
    for (const canChat of ["false", "missing"]) {
      await page.evaluate((canChat) => {
        if (canChat === "missing") delete window.inbox.questions[0].canChat;
        else window.inbox.questions[0].canChat = false;
      }, canChat);
      await ui.getByRole("button", { name: "Review question" }).click();
      await settled(page);
      assert.equal(await ui.locator("#answer").count(), 0, canChat);
      assert.equal(await aside.getByText(note, { exact: true }).count(), 1);
      assert.equal(
        await aside.getByRole("button", { name: "Discuss in chat" }).count(),
        1,
      );
    }
    // Revoked between showing the answer box and sending.
    await page.evaluate(() => (window.inbox.questions[0].canChat = true));
    await ui.getByRole("button", { name: "Review question" }).click();
    await settled(page);
    await ui.locator("#answer").fill("Annual software license");
    await page.evaluate(() => (window.inbox.questions[0].canChat = false));
    await ui.getByRole("button", { name: "Send answer to Norman" }).click();
    assert.equal(await settled(page), note);
    assert.equal(await ui.locator("#answer").count(), 0);
    assert.equal((await mutations(page)).length, 0);
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
});

test("approval review shows names, amount and date instead of raw ids", async () => {
  const { page, ui, errors } = await fixture();
  try {
    const ids = {
      companyCategory: "6b1f0c2e-4d7a-4f55-9d7e-0c1d2e3f4a5b",
      vendor: "0f9e8d7c-6b5a-4c3d-9e2f-1a2b3c4d5e6f",
      currentVendor: "9d2c1b0a-8f7e-4d6c-9b5a-493827160504",
      client: "5e4d3c2b-1a09-4f8e-8d7c-6b5a49382716",
    };
    await page.evaluate((ids) => {
      // Shapes of RuleExecutionSerializer.transaction and the labelled plan.
      const transaction = {
        publicId: "7a6b5c4d-3e2f-4a1b-9c8d-7e6f5a4b3c2d",
        description: "Adobe subscription",
        amount: "-59.49",
        cashflowType: "EXPENSE",
        valueDate: "2026-09-12T10:00:00+00:00",
      };
      window.inbox.approvals[0].transaction = transaction;
      window.inbox.approvals.push({
        publicId: "approval-2",
        ruleName: "Client payments",
        transaction: {
          description: "Invoice 2026-041",
          amount: "1200.00",
          cashflowType: "INCOME",
          valueDate: "2026-08-31",
        },
      });
      window.detail.before = {
        category: null,
        companyCategory: { name: "Office supplies" },
        companyCategoryLabel: "4930 Office supplies",
        vendor: ids.currentVendor,
        vendorLabel: "Adobe Inc.",
        client: null,
      };
      Object.assign(window.detail.execution, {
        transaction,
        actionsPlanned: [
          {
            type: "set_category",
            params: { category: null, companyCategory: ids.companyCategory },
            labels: { companyCategory: "4964 Software & SaaS" },
          },
          {
            type: "assign_vendor",
            params: { vendor: ids.vendor },
            labels: { vendor: "Adobe Systems Software Ireland" },
          },
          // Without a label the raw value stays visible.
          { type: "assign_client", params: { client: ids.client } },
        ],
      });
    }, ids);
    await ui.getByRole("button", { name: "Refresh", exact: true }).click();
    await settled(page);
    const rows = await page
      .frames()[1]
      .evaluate(() =>
        [...document.querySelectorAll("article")]
          .filter((card) => card.querySelector("[data-execution]"))
          .map((card) => card.querySelector("p").innerText),
      );
    assert.equal(rows.length, 2);
    assert.match(rows[0], /^Adobe subscription\n-59,49\s€ · 12\.09\.2026$/);
    assert.match(rows[1], /^Invoice 2026-041\n\+1\.200,00\s€ · 31\.08\.2026$/);
    await ui.getByRole("button", { name: "Review changes" }).first().click();
    await settled(page);
    const detail = await page.frames()[1].evaluate(() => ({
      header: document.querySelector("aside h2 + p").innerText,
      table: [...document.querySelectorAll("aside tbody tr")].map((row) =>
        [...row.cells].map((cell) => cell.innerText),
      ),
      text: document.querySelector("aside").innerText,
    }));
    assert.match(
      detail.header,
      /^Adobe subscription\n-59,49\s€ · Expense · 12\.09\.2026$/,
    );
    assert.deepEqual(detail.table, [
      [
        "Set category",
        "—\n4930 Office supplies",
        "Category: —\nCompany category: 4964 Software & SaaS",
      ],
      ["Assign vendor", "Adobe Inc.", "Vendor: Adobe Systems Software Ireland"],
      ["Assign client", "—", `Client: ${ids.client}`],
    ]);
    for (const id of [ids.companyCategory, ids.vendor, ids.currentVendor])
      assert.equal(detail.text.includes(id), false, id);
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
});

test("a warning raised by a user refresh is not replaced by its success status", async () => {
  const { page, ui, errors } = await fixture(1100, { clock: true });
  try {
    const refreshNow = async () => {
      await ui.getByRole("button", { name: "Refresh", exact: true }).click();
      await idle(page);
      return (await view(page)).status;
    };
    await drafted(page, ui);
    await page.evaluate(
      (question) => (window.inbox.questions[0].blockedDetail = question),
      QUESTION_B,
    );
    assert.equal(
      await refreshNow(),
      "This workflow question changed. Review your answer before sending.",
    );
    // Consent on one approval; opening another one is not a change to it.
    await page.evaluate(() => {
      window.inbox.approvals.push({
        publicId: "approval-2",
        ruleName: "Client payments",
        transaction: { description: "Invoice 2026-041" },
      });
      window.hooks.get_norman_approval_data = ({ execution_id }) =>
        execution_id === "approval-2"
          ? {
              ...window.detail,
              execution: {
                ...window.detail.execution,
                publicId: "approval-2",
                ruleName: "Client payments",
              },
            }
          : window.detail;
    });
    await refreshNow();
    await ui.getByRole("button", { name: "Review changes" }).first().click();
    await idle(page);
    await ui.locator("#confirm").check();
    await ui.getByRole("button", { name: "Review changes" }).nth(1).click();
    await idle(page);
    assert.equal((await view(page)).status, "Updated from Norman.");
    assert.equal(await ui.locator("aside h2").innerText(), "Client payments");
    await ui.locator("#confirm").check();
    await page.evaluate(() => (window.detail.before.vatRate = 0));
    await ui.getByRole("button", { name: "Review changes" }).first().click();
    await idle(page);
    await ui.locator("#confirm").check();
    await page.evaluate(() => (window.detail.before.vatRate = 19));
    assert.equal(
      await refreshNow(),
      "This approval changed. Review the current values and confirm again.",
    );
    assert.equal((await view(page)).confirm, false);
    assert.equal((await mutations(page)).length, 0);
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
});

test("the page returned by the server becomes the current page", async () => {
  const { page, ui, errors } = await fixture(1100, { clock: true });
  try {
    const pages = async () =>
      (await toolCalls(page, "get_norman_inbox_data")).map(
        (call) => call.params.arguments.page,
      );
    await ui.getByRole("button", { name: "More approvals" }).click();
    await idle(page);
    await ui.getByRole("button", { name: "Previous approvals" }).waitFor();
    // Page 2 no longer exists (its last item was decided); the server clamps.
    await page.evaluate(
      () =>
        (window.hooks.get_norman_inbox_data = ({ page }) => ({
          ...window.inbox,
          pagination: { page: Math.min(page, 1), hasNext: false },
        })),
    );
    await page.clock.runFor(30_001);
    await idle(page);
    assert.equal(
      await ui.getByRole("button", { name: "Previous approvals" }).count(),
      0,
    );
    await page.clock.runFor(30_001);
    await idle(page);
    assert.deepEqual(await pages(), [1, 2, 2, 1]);
    // A page number sent as text still counts as a number.
    await page.evaluate(
      () =>
        (window.hooks.get_norman_inbox_data = ({ page }) => ({
          ...window.inbox,
          pagination: { page: String(page), hasNext: true },
        })),
    );
    await ui.getByRole("button", { name: "Refresh", exact: true }).click();
    await idle(page);
    await ui.getByRole("button", { name: "More approvals" }).click();
    await idle(page);
    assert.deepEqual((await pages()).slice(-2), [1, 2]);
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
});

test("an expired Norman session stops polling until the user interacts", async () => {
  const { page, ui, errors } = await fixture(1100, { clock: true });
  try {
    const expired =
      "Your Norman session expired. Please disconnect and reconnect the Norman connector in your AI client to re-authenticate.";
    const reads = async () =>
      (await toolCalls(page, "get_norman_inbox_data")).length;
    await page.evaluate(
      (error) =>
        (window.hooks.get_norman_inbox_data = () => ({
          error,
          reconnect: true,
        })),
      expired,
    );
    await page.clock.runFor(30_001);
    await until(page, quiet, undefined, "the failed poll");
    assert.equal((await view(page)).status, expired);
    assert.match(
      await ui.locator("#freshness").innerText(),
      /Auto refresh paused until you use the Inbox again/,
    );
    assert.equal(await reads(), 2);
    // No polls, focus or visibility wake-ups while the session is expired.
    await page.clock.runFor(600_000);
    await page
      .frames()[1]
      .evaluate(() => window.dispatchEvent(new Event("focus")));
    await setShown(page, false);
    await setShown(page, true);
    await page.clock.runFor(1);
    await flush(page);
    assert.equal(await reads(), 2);
    // After reconnecting, the user refreshes and polling resumes.
    await page.evaluate(() => delete window.hooks.get_norman_inbox_data);
    await ui.getByRole("button", { name: "Refresh", exact: true }).click();
    await idle(page);
    assert.equal((await view(page)).status, "Updated from Norman.");
    await page.clock.runFor(30_001);
    await idle(page);
    assert.equal(await reads(), 4);
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
});

test("tool errors show the API's own message and never a raw URL", async () => {
  const { page, ui, errors } = await fixture();
  try {
    const api = "https://api.norman.finance/api/v1";
    for (const [result, message] of [
      [
        {
          error: `Request failed: 404 Client Error: Not Found for url: ${api}/accounting/rule-executions/?page=9`,
          detail: { detail: "Invalid page." },
        },
        "Invalid page.",
      ],
      [
        {
          error: `Request failed: 409 Client Error: Conflict for url: ${api}/assistant/workflow-runs/`,
          detail: { message: "Norman is busy. Try again shortly.", code: "busy" },
        },
        "Norman is busy. Try again shortly.",
      ],
      [
        {
          error: `Request failed: 400 Client Error: Bad Request for url: ${api}/x/`,
          detail: "Page size must be positive.",
        },
        "Page size must be positive.",
      ],
      [
        {
          error: `Request failed: 502 Server Error: Bad Gateway for url: ${api}/x/`,
          detail: "<html><body><h1>502 Bad Gateway</h1></body></html>",
        },
        "Request failed: 502 Server Error: Bad Gateway",
      ],
      [
        { error: `Norman is unavailable (${api.replace("/api/v1", "")}/status).` },
        "Norman is unavailable.",
      ],
    ]) {
      await page.evaluate(
        (result) => (window.hooks.get_norman_inbox_data = () => result),
        result,
      );
      await ui.getByRole("button", { name: "Refresh", exact: true }).click();
      // The Refresh action or a follow-up poll may report the failure.
      assert.equal(
        (await settled(page)).replace(/^Could not refresh: /, ""),
        message,
      );
    }
    await page.evaluate((api) => {
      delete window.hooks.get_norman_inbox_data;
      window.detail.execution.error = `Vendor lookup failed for url: ${api}/vendors/0f9e8d7c/`;
      window.hooks.approve_rule_execution = () => ({
        error: `Request failed: 400 Client Error: Bad Request for url: ${api}/accounting/rule-executions/approval-1/approve/`,
        detail: { detail: "This execution is no longer awaiting review." },
      });
    }, api);
    await ui.getByRole("button", { name: "Review changes" }).click();
    await settled(page);
    assert.equal(
      await ui.locator("aside p.error").innerText(),
      "Vendor lookup failed",
    );
    await ui.locator("#confirm").check();
    await ui.getByRole("button", { name: "Approve execution" }).click();
    assert.equal(
      await settled(page),
      "This execution is no longer awaiting review.",
    );
    assert.doesNotMatch(
      await page.frames()[1].evaluate(() => document.body.innerText),
      /https?:|for url/i,
    );
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
});

for (const lifecycle of ["pagehide", "ui/resource-teardown"])
  test(`${lifecycle} disposes polling instead of leaving a background loop`, async () => {
    const { page, ui, errors } = await fixture(1100, { clock: true });
    try {
      if (lifecycle === "pagehide")
        await page
          .frames()[1]
          .evaluate(() => window.dispatchEvent(new Event("pagehide")));
      else
        await page.evaluate(() =>
          document.querySelector("iframe").contentWindow.postMessage(
            {
              jsonrpc: "2.0",
              id: 900,
              method: "ui/resource-teardown",
              params: {},
            },
            "*",
          ),
        );
      await ui.getByText(/Auto refresh paused/).waitFor();
      const before = (await toolCalls(page, "get_norman_inbox_data")).length;
      await page.clock.runFor(90_001);
      await page
        .frames()[1]
        .evaluate(() => window.dispatchEvent(new Event("focus")));
      await page.clock.runFor(1);
      await flush(page);
      assert.equal(
        (await toolCalls(page, "get_norman_inbox_data")).length,
        before,
      );
      assert.equal((await mutations(page)).length, 0);
      assert.deepEqual(errors, []);
    } finally {
      await page.close();
    }
  });
