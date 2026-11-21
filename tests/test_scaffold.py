"""Static checks on the Home Assistant files (no Home Assistant import needed)."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "bougerv_mppt"


def test_manifest() -> None:
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["domain"] == "bougerv_mppt"
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "local_polling"
    assert manifest["bluetooth"] == [
        {"local_name": "ChargePro*", "connectable": True},
        {"service_uuid": "0000ffe0-0000-1000-8000-00805f9b34fb", "connectable": True},
    ]
    for key in ("version", "codeowners", "issue_tracker", "documentation"):
        assert key in manifest


def test_versions_match() -> None:
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{manifest["version"]}"' in pyproject


def test_hacs_json() -> None:
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert hacs["content_in_root"] is False


def test_modules_parse() -> None:
    for path in INTEGRATION.rglob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_translations_match_strings() -> None:
    strings = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
    english = json.loads((INTEGRATION / "translations" / "en.json").read_text(encoding="utf-8"))
    assert english == strings


def test_every_translation_key_has_a_string() -> None:
    strings = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
    for platform in ("sensor", "binary_sensor"):
        source = (INTEGRATION / f"{platform}.py").read_text(encoding="utf-8")
        keys = set(re.findall(r'translation_key="([a-z_]+)"', source))
        keys |= set(re.findall(r'_\w+\("([a-z_]+)", "', source))
        assert keys, platform
        assert keys <= set(strings["entity"][platform]), keys - set(strings["entity"][platform])


def test_charge_stage_states_translated() -> None:
    from custom_components.bougerv_mppt.core.models import CHARGE_STAGE_OPTIONS

    strings = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
    assert set(strings["entity"]["sensor"]["charge_stage"]["state"]) == set(CHARGE_STAGE_OPTIONS)


def test_config_flow_errors_translated() -> None:
    source = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
    strings = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
    errors = set(re.findall(r'return None, "([a-z_]+)"', source))
    assert errors <= set(strings["config"]["error"])


def test_manifest_key_order() -> None:
    """hassfest wants domain, name, then the rest sorted."""
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    keys = list(manifest)
    assert keys[:2] == ["domain", "name"]
    assert keys[2:] == sorted(keys[2:])


def test_services_have_strings() -> None:
    strings = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
    text = (INTEGRATION / "services.yaml").read_text(encoding="utf-8")
    services = re.findall(r"^([a-z_]+):$", text, re.M)
    fields = re.findall(r"^    ([a-z_]+):$", text, re.M)
    assert services == list(strings["services"])
    assert set(fields) == set(strings["services"]["read_registers"]["fields"])
