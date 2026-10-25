---
name: pl-opening-balance
description: A Polish sp. z o.o. brings its opening balance (bilans otwarcia) and the year's turnover from its previous books into PL_FULL, from the zestawienie obrotów i sald (CSV/XLSX) or typed balances. Preview, mapping to PL_FULL, then apply on the owner's word.
version: 1.0.0
disable-model-invocation: true
argument-hint: "[trial balance file]"
metadata:
  openclaw:
    emoji: "\U0001F4D6"
    homepage: https://norman.finance
    requires:
      mcp:
        - norman-finance
---

Help the owner of a Polish sp. z o.o. bring the balances of its previous books into Norman. The books are continuous: the year opens with last year's closing balances (art. 5 ust. 1 and art. 12 ust. 1 of the accounting act), so Norman needs the trial balance (zestawienie obrotów i sald) on the day before its books in Norman start.

1. **Status first**: `get_accounting_setup` shows the start of the books in Norman, whether an opening balance is in and whether it was made for another start (`stale`). Without a start month the owner chooses it in Account → Taxes → «Księgi w Normanie».

2. **The file**: the trial balance from the previous program (Comarch Optima, Symfonia, enova365, wFirma, inFakt, Rewizor) as CSV or XLSX, on the day before the start, best with the BO columns. A PDF cannot be read by columns: ask for the CSV or XLSX export. A small company may type the balances instead (`manual_balances`). Never record these files as documents.

3. **Preview**: `preview_accounting_cutover` with `opening_file_ref` (or `manual_balances`), no mode or dates. Show the owner:
   - each source account with the PL_FULL account it maps to and how: `rule`, `ai` (a suggestion), `owner`, `previous`;
   - Wn = Ma, the BO on 1 January and the turnover until the day before the start;
   - the errors and warnings in the API's words.
   Accounts Norman has no place for (kapitał zapasowy, rezerwy, rozliczenia międzyokresowe, kredyty) stay unmapped: never map them to a look-alike to get past the check. Clearing accounts that cancel out (490 with zespół 5) may be left out with `-`.

4. **Fixed assets**: balances on 010/020 depreciate on only once the assets are listed as taken over (`takeover_assets`: name, account, kind, entry date, initial value, umorzenie, annual rate). Ask for the asset register (ewidencja środków trwałych) when the preview warns.

5. **Apply** only when the owner asked for it after seeing the preview: `apply_accounting_cutover` with `confirmed=true`, the same file and the preview's whole `account_mapping`. It replaces an earlier import of the year.

6. **After**: Norman's own postings before the start leave the journal; the CIT takes the revenue and costs before the start from the import unless the owner entered them, and still needs the CIT advances of those months in «Księgi w Normanie». Point to «Księgi rachunkowe» → «Obroty i salda» in Norman to check the BO.
