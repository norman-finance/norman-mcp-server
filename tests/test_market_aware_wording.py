"""The texts the model reads describe both markets: no German-only filing for a Polish company.

The public server lists every tool to every company, German or Polish; a German procedure refuses a
Polish company only when it is called (country_scope). So a shared tool or skill that names a German
filing (the UStVA, ZM, EÜR, ELSTER, the Finanzamt) says it is German or names the Polish counterpart in
the same sentence, a text about a Polish company never offers it a UStVA, and every German-only tool
and skill says "Germany only" plainly.
"""

import re
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

from tests.mcp_harness import FakeApi, call_tool, structured
from norman_mcp.prompts.templates import _load_skills
from norman_mcp.server import mcp
from norman_mcp.tools.country_scope import (
    ALSO_POLISH,
    GERMAN_ONLY_MODULES,
    GERMAN_ONLY_TOOLS,
    GERMANY_AND_POLAND_NOTE,
    GERMANY_ONLY_NOTE,
)

PLUGIN_SKILLS = Path(__file__).resolve().parents[1] / "openai-plugin" / "skills"

# The German filings and authorities a Polish company never has.
GERMAN_FILING = re.compile(r"UStVA|ELSTER|Finanzamt|\bZM\b|EÜR")
# The same sentence says the filing is German, or names its Polish counterpart.
MARKET_NAMED = re.compile(r"German|Germany|\bDE\b|GmbH|\bUG\b|Polish|Poland|\bPL\b|JPK|VAT-UE")
# A sentence about a Polish company.
POLISH = re.compile(r"Polish|Poland|\bPL\b|\bJDG\b|sp\. z o\.o\.")
# "never a UStVA": a negation is no offer.
NEGATION = re.compile(r"\b(?:never|not|no|none|without)\b", re.IGNORECASE)
# A skill about a German procedure, and the plain words that keep it from a Polish company.
GERMAN_PROCEDURE = re.compile(
    r"UStVA|ELSTER|Finanzamt|\bZM\b|EÜR|DATEV|\bSKR|Gewerbe|Fragebogen|GmbH|\bUG\b|Lohn|SEPA"
)
GERMANY_ONLY = re.compile(r"Germany only|German (?:companies|SMEs?|clients?) only")
SKILL_MARKET_NAMED = re.compile(
    GERMANY_ONLY.pattern + r"|for a German company|Polish|Poland|JPK"
)
LIST_ITEM = re.compile(r"^(?:[-*]|\d+\.|#+)\s")


def _sentences(text: str) -> list[str]:
    flat = " ".join(text.split())
    return [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z*`(\[])", flat) if s]


def _offers_a_german_filing(sentence: str, context: str = "") -> bool:
    return bool(GERMAN_FILING.search(sentence)) and not MARKET_NAMED.search(f"{context} {sentence}")


def _offers_a_polish_company_a_ustva(sentence: str) -> bool:
    return "UStVA" in sentence and bool(POLISH.search(sentence)) and not (
        NEGATION.search(sentence) or "German" in sentence
    )


def _is_german_only(tool: Any) -> bool:
    return tool.name in GERMAN_ONLY_TOOLS or tool.fn.__module__ in GERMAN_ONLY_MODULES


def _descriptions(node: Any, path: str) -> Iterator[tuple[str, str]]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "description" and isinstance(value, str):
                yield path, value
            elif isinstance(value, (dict, list)):
                yield from _descriptions(value, path if key == "properties" else f"{path}.{key}")
    elif isinstance(node, list):
        for item in node:
            yield from _descriptions(item, path)


def _shared_texts() -> Iterator[tuple[str, str]]:
    """Every description of a tool that serves German and Polish companies alike."""
    for tool in mcp._tool_manager._tools.values():
        if _is_german_only(tool):
            continue
        yield tool.name, tool.description or ""
        yield from _descriptions(tool.parameters, tool.name)


def _plugin_skills() -> list[dict]:
    skills = []
    for path in sorted(PLUGIN_SKILLS.glob("*/SKILL.md")):
        meta, _, body = path.read_text(encoding="utf-8").removeprefix("---\n").partition("\n---\n")
        skills.append({"name": path.parent.name, "description": yaml.safe_load(meta)["description"], "body": body})
    return skills


ALL_SKILLS = _load_skills() + _plugin_skills()


def _skill_units(body: str) -> Iterator[tuple[str, str]]:
    """Each line of a skill body with the list items it sits under, which may name the market for it."""
    parents: list[tuple[int, str]] = []
    for line in body.splitlines():
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        while parents and parents[-1][0] >= indent:
            parents.pop()
        yield line.strip(), " ".join(text for _, text in parents)
        if LIST_ITEM.match(line.lstrip()):
            parents.append((indent, line.strip()))


def test_a_shared_tool_never_offers_an_unqualified_german_filing():
    offers = [
        (where, sentence)
        for where, text in _shared_texts()
        for sentence in _sentences(text)
        if _offers_a_german_filing(sentence) or _offers_a_polish_company_a_ustva(sentence)
    ]

    assert offers == []


def test_every_german_only_tool_says_so():
    tools = [tool for tool in mcp._tool_manager._tools.values() if _is_german_only(tool)]

    assert tools
    assert [
        tool.name
        for tool in tools
        if not (tool.description or "").startswith(
            GERMANY_AND_POLAND_NOTE if tool.name in ALSO_POLISH else GERMANY_ONLY_NOTE
        )
    ] == []
    # The note opens the description; the tool's own text follows it unchanged.
    assert mcp._tool_manager._tools["submit_tax_report"].description.startswith(
        "Germany only. Submit a tax report to the Finanzamt."
    )


def test_the_shared_tools_name_each_market_s_filing():
    texts = {where: " ".join(text.split()) for where, text in _shared_texts()}

    assert "a Polish VAT payer's JPK_V7M or JPK_V7K, due the 25th" in texts["get_vat_next_report"]
    assert "JPK_V7, VAT-UE, PIT and CIT advances, ZUS DRA" in texts["update_company_details.notify_tax_deadlines"]
    assert "a German UStVA, a Polish JPK_V7M or JPK_V7K" in texts["list_pending_approvals"]
    assert "Poland 0, 5, 8, 23" in texts["create_product"]
    assert "German companies only: a Polish company uses day_of_month" in texts["schedule_workflow.cadence"]
    assert "Germany only: a Polish company's urząd skarbowy" in texts["get_tax_offices"]
    assert texts["render_tax_preview"].startswith("German companies only")
    assert "PL_KPIR or PL_FULL" in texts["update_transaction.company_category_id"]
    assert "faktura korygująca" in texts["create_credit_note"]


def test_every_skill_about_a_german_procedure_names_its_market():
    unnamed = [
        skill["name"]
        for skill in ALL_SKILLS
        if GERMAN_PROCEDURE.search(skill["description"]) and not SKILL_MARKET_NAMED.search(skill["description"])
    ]

    assert unnamed == []


@pytest.mark.parametrize(
    "name",
    [
        "accounting-cutover",
        "company-incorporation",
        "corporate-tax-registration",
        "gewerbe-registration",
        "run-payroll-month",
        "suggest-category",
        "ta-datev-preparation",
        "tax-preview",
        "ledger-explorer",
    ],
)
def test_a_german_only_skill_says_so(name):
    [skill] = [skill for skill in ALL_SKILLS if skill["name"] == name]

    assert GERMANY_ONLY.search(skill["description"])


def test_no_skill_offers_a_polish_company_a_german_filing():
    offers = [
        (skill["name"], sentence)
        for skill in ALL_SKILLS
        for line, parents in _skill_units(skill["body"])
        for sentence in _sentences(line)
        if _offers_a_polish_company_a_ustva(sentence)
        # A German-only skill's own steps are German by its description.
        or (not GERMANY_ONLY.search(skill["description"]) and _offers_a_german_filing(sentence, parents))
    ]

    assert offers == []


def test_the_tax_report_skill_serves_both_markets():
    [skill] = [skill for skill in _load_skills() if skill["name"] == "tax-report"]

    assert "Polish companies: the JPK_V7 and VAT-UE" in skill["description"]
    assert "German companies: VAT (UStVA, ZM, Umsatzsteuer)" in skill["description"]
    assert "`get_polish_jpk_register`" in skill["body"]
    assert "There is no Polish signing or submission tool here" in skill["body"]
    assert "PIT and CIT advances and ZUS DRA: 20th of the following month" in skill["body"]
    assert "German tax reports" not in skill["description"]


def test_the_compliance_check_names_polish_and_german_deadlines():
    [skill] = [skill for skill in _load_skills() if skill["name"] == "ta-tax-compliance"]

    assert "JPK_V7M or JPK_V7K and VAT-UE: 25th of the following month" in skill["body"]
    assert "Monthly USt-VA: 10th of the following month" in skill["body"]


def test_categorizing_sends_a_polish_company_to_its_own_chart():
    [skill] = [skill for skill in _load_skills() if skill["name"] == "categorize-transactions"]

    assert "**Sp. z o.o.** (`isSme: true`, `country: PL`)" in skill["body"]
    assert "The SKR tools are German and not available for it" in skill["body"]
    assert "**JDG** (`isSme: false`, `country: PL`, `usesCompanyChart: true`)" in skill["body"]


@pytest.mark.parametrize(
    ("country", "named", "never"),
    [
        ("PL", ["Tax ID (NIP) is missing", "VAT-UE registration"], ["Finanzamt", "Steuernummer", "USt-IdNr"]),
        ("DE", ["Tax ID (Steuernummer) is missing — register with Finanzamt", "USt-IdNr."], ["NIP", "VAT-UE"]),
    ],
)
def test_the_compliance_status_names_the_client_s_own_registration(country, named, never):
    def respond(method, url, kwargs):
        if url.endswith("/companies/client-company/"):
            return {"country": country, "taxNumber": "", "vatNumber": "", "taxState": None}
        return {"results": []}

    result = structured(call_tool("get_tax_compliance_status", {"company_id": "client-company"}, FakeApi(respond)))
    items = " ".join(result["actionItems"])

    assert result["registration"]["country"] == country
    assert all(text in items for text in named)
    assert not any(text in items for text in never)
