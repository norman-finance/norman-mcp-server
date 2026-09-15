import asyncio
import json
from pathlib import Path
from zipfile import ZipFile

from scripts.chatgpt_submission import build_submission
from scripts.package_chatgpt_skills import build_package


def test_submission_artifact_matches_reviewed_runtime_inventory():
    generated = asyncio.run(build_submission())
    stored = json.loads(
        (Path(__file__).resolve().parents[1] / "chatgpt-app-submission.json").read_text()
    )
    assert stored == generated
    assert len(generated["test_cases"]) == 5
    assert len(generated["negative_test_cases"]) == 3
    assert len(generated["app_info"]["subtitle"]) <= 30
    for test in generated["test_cases"]:
        for name in test["tools_triggered"].split(", "):
            assert name in generated["tools"]
    assert "pay_bill" not in generated["tools"]
    assert "set_corporate_people" not in generated["tools"]


def test_chatgpt_skill_package_overrides_sensitive_flows_only(tmp_path):
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "skills.zip"
    count = build_package(output)
    with ZipFile(output) as package:
        assert len(package.namelist()) == count
        for name in ("company-incorporation", "gewerbe-registration", "corporate-tax-registration"):
            content = package.read(f"skills/{name}/SKILL.md").decode()
            assert "get_norman_workspace" in content
            assert "version: 2.0.1" in content
            assert content == (root / "chatgpt" / "skills" / name / "SKILL.md").read_text()
        assert (
            package.read("skills/create-invoice/SKILL.md")
            == (root / "skills/create-invoice/SKILL.md").read_bytes()
        )
