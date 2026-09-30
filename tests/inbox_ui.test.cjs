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

async function fixture(width = 1100) {
  const page = await browser.newPage({ viewport: { width, height: 1000 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.setContent(
    '<iframe title="Norman Inbox" style="border:0;width:100%;height:960px"></iframe>',
  );
  await page.evaluate(() => {
    window.calls = [];
    window.mode = "";
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
      if (!m.id) return;
      let result = {};
      if (m.method === "tools/call") {
        const { name, arguments: args } = m.params;
        if (name === "get_norman_inbox_data") {
          window.inbox.pagination.page = args.page;
          result = window.inbox;
        }
        if (name === "get_norman_approval_data") result = window.detail;
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
        result = { structuredContent: structuredClone(result), content: [] };
      }
      e.source.postMessage({ jsonrpc: "2.0", id: m.id, result }, "*");
    });
  });
  const html = readFileSync(
    join(__dirname, "../norman_mcp/apps/inbox.html"),
    "utf8",
  );
  await page
    .locator("iframe")
    .evaluate((frame, html) => (frame.srcdoc = html), html);
  const ui = page.frameLocator("iframe");
  await ui.getByRole("button", { name: "Review changes" }).waitFor();
  return { page, ui, errors };
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
