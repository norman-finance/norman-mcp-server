---
name: ta-tax-compliance
description: Tax compliance check for a client company. Checks all tax periods, identifies unfiled or overdue reports, verifies tax registration, and generates a compliance summary. Use when a tax advisor asks about tax deadlines, compliance status, or filing obligations.
version: 1.0.0
metadata:
  openclaw:
    emoji: "\U00002705"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Perform a thorough tax compliance check for the tax advisor:

## Step 1: Check compliance status
- Call `get_tax_compliance_status` with the active company ID
- This returns tax reports status, tax settings, and registration info

## Step 2: Review tax settings
- Call `list_tax_settings` to verify the reporting frequency and VAT configuration
- Check if the settings match the company type (e.g., Kleinunternehmer vs. VAT subject)

## Step 3: Verify registration
Check the following registration details:
- **Steuernummer** (tax ID): Is it set? Is it in the correct format for the tax state?
- **USt-IdNr.** (VAT ID): Is it set? Is it needed based on EU trade activity?
- **Tax state** (Bundesland): Is it correctly assigned?

## Step 4: Analyze report filing status
For each unfiled report:
- Identify the report type (USt-VA, EÜR, annual VAT, trade tax)
- Note the period and due date
- Flag if it is overdue

## Step 5: Present the compliance report

### Registration Status
- Tax ID: ✅/❌ with value if present
- VAT ID: ✅/❌ with value if present
- Tax state: ✅/❌ with name

### Filing Status
| Report Type | Period | Status | Due Date |
|-------------|--------|--------|----------|
| ...         | ...    | ...    | ...      |

### Upcoming Deadlines
- List the next 3 filing deadlines with dates
- Note the standard deadlines:
  - Monthly USt-VA: 10th of the following month (+ Dauerfristverlängerung = 10th of the month after)
  - Quarterly USt-VA: 10th of the month after the quarter ends
  - Annual USt: July 31 of the following year (with advisor extension: end of February of the year after)

### Action Items
Prioritized list:
1. Overdue reports that must be filed immediately
2. Reports due within the next 30 days
3. Registration issues that need attention
4. Settings that may need adjustment

Be precise with dates and report periods. Use German tax terminology where appropriate.
