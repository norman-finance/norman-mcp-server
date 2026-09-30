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

async function fixture(width = 1100, { clock = false } = {}) {
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
  await page.evaluate(() => {
    window.calls = [];
    window.mode = "";
    window.hooks = {};
    window.holdNames = [];
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
  });
  const html = readFileSync(
    join(__dirname, "../norman_mcp/apps/inbox.html"),
    "utf8",
  ).replace("const state = {", "const state = window.__inboxTestState = {");
  await page
    .locator("iframe")
    .evaluate((frame, html) => (frame.srcdoc = html), html);
  const ui = page.frameLocator("iframe");
  await ui.getByRole("button", { name: "Review changes" }).waitFor();
  await idle(page);
  return { page, ui, errors };
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
    for (let i = 0; i < 2; i++) {
      await page.clock.runFor(30_001);
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
    await page
      .frames()[1]
      .evaluate(() => window.dispatchEvent(new Event("focus")));
    await page.clock.runFor(1);
    await idle(page);
    assert.equal(
      (await toolCalls(page, "get_norman_inbox_data")).length,
      resumed + 1,
    );
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
    await page.clock.runFor(29_999);
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
      ["ui/initialize", "ui/notifications/initialized"],
    );
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
