from __future__ import annotations

import json
import uuid
from pathlib import Path


def validate_pbip(pbip_path: Path) -> dict[str, any]:
    base_dir = pbip_path.parent
    report_dir = base_dir / "CRIC_Analytics_Dashboard_v2.Report"
    model_dir = base_dir / "CRIC_Analytics_Dashboard_v2.SemanticModel"

    results = {"checks": [], "errors": []}

    def check(name: str, passed: bool, detail: str) -> None:
        results["checks"].append({"name": name, "passed": passed, "detail": detail})
        if not passed:
            results["errors"].append(f"{name}: {detail}")

    # 1. PBIP file
    if not pbip_path.exists():
        check("PBIP File Existence", False, f"File missing at {pbip_path}")
        return results
    check("PBIP File Existence", True, f"Found {pbip_path.name}")

    try:
        with open(pbip_path, "r", encoding="utf-8") as f:
            pbip_data = json.load(f)
        check("PBIP JSON Parsing", True, "Successfully parsed JSON")
    except Exception as e:
        check("PBIP JSON Parsing", False, f"JSON parse error: {e}")
        return results

    artifacts = pbip_data.get("artifacts", [])
    report_artifact = next((a["report"]["path"] for a in artifacts if "report" in a), None)
    if report_artifact:
        resolved_report = (base_dir / report_artifact).resolve()
        check("PBIP Report Artifact", resolved_report.exists(), f"Points to {resolved_report}")
    else:
        check("PBIP Report Artifact", False, "Missing report artifact declaration in PBIP")

    # 2. .platform files
    logical_ids = {}
    for p_file, expected_type in [
        (report_dir / ".platform", "Report"),
        (model_dir / ".platform", "SemanticModel"),
    ]:
        p_name = f"{p_file.parent.name}/.platform"
        if not p_file.exists():
            check(f"{p_name} Existence", False, "File missing")
            continue
        check(f"{p_name} Existence", True, "File present")

        try:
            with open(p_file, "r", encoding="utf-8") as f:
                p_data = json.load(f)
            check(f"{p_name} JSON Parse", True, "Parsed successfully")
        except Exception as e:
            check(f"{p_name} JSON Parse", False, f"JSON error: {e}")
            continue

        expected_schema = "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json"
        actual_schema = p_data.get("$schema")
        check(f"{p_name} Schema", actual_schema == expected_schema, f"{actual_schema}")

        actual_type = p_data.get("metadata", {}).get("type")
        check(f"{p_name} Metadata Type", actual_type == expected_type, f"Expected {expected_type}, got {actual_type}")

        display_name = p_data.get("metadata", {}).get("displayName")
        check(f"{p_name} Display Name", bool(display_name), f"'{display_name}'")

        ver = p_data.get("config", {}).get("version")
        check(f"{p_name} Config Version", ver == "2.0", f"version '{ver}'")

        lid = p_data.get("config", {}).get("logicalId")
        try:
            parsed_uuid = uuid.UUID(lid)
            # Ensure it is standard 36-char hyphenated format
            is_valid_format = len(lid) == 36 and str(parsed_uuid) == lid.lower()
            check(f"{p_name} LogicalId GUID", is_valid_format, f"Valid GUID {lid} (version {parsed_uuid.version})")
            if is_valid_format:
                logical_ids[expected_type] = lid
        except Exception as e:
            check(f"{p_name} LogicalId GUID", False, f"Invalid GUID '{lid}': {e}")

    # Distinct logicalIds
    if len(logical_ids) == 2:
        unique = len(set(logical_ids.values())) == 2
        check("Artifact LogicalId Uniqueness", unique, f"Report: {logical_ids['Report']}, Model: {logical_ids['SemanticModel']}")

    # 3. definition.pbir
    pbir_file = report_dir / "definition.pbir"
    if pbir_file.exists():
        try:
            with open(pbir_file, "r", encoding="utf-8") as f:
                pbir_data = json.load(f)
            check("definition.pbir JSON Parse", True, "Parsed successfully")
            rel_path = pbir_data.get("datasetReference", {}).get("byPath", {}).get("path")
            resolved_model = (report_dir / rel_path).resolve()
            check("Report-to-Model Dataset Reference", resolved_model == model_dir.resolve(), f"Resolves to {resolved_model}")
        except Exception as e:
            check("definition.pbir JSON Parse", False, f"Error: {e}")
    else:
        check("definition.pbir Existence", False, "Missing definition.pbir")

    # 4. Eight Report Pages and 64 Visuals
    pages_json = report_dir / "definition" / "pages" / "pages.json"
    if pages_json.exists():
        try:
            with open(pages_json, "r", encoding="utf-8") as f:
                pj = json.load(f)
            check("pages.json JSON Parse", True, "Parsed successfully")
            page_order = pj.get("pageOrder", [])
            check("Report Page Count (8 pages)", len(page_order) == 8, f"{len(page_order)} pages registered")

            total_visuals = 0
            all_page_files_valid = True
            for pid in page_order:
                p_dir = report_dir / "definition" / "pages" / pid
                p_file = p_dir / "page.json"
                if not p_file.exists():
                    all_page_files_valid = False
                v_dir = p_dir / "visuals"
                if v_dir.exists():
                    for vf in v_dir.glob("*/visual.json"):
                        with open(vf, "r", encoding="utf-8") as vfp:
                            json.load(vfp)
                        total_visuals += 1
            check("Report Pages Directory Structure", all_page_files_valid, "All 8 page directories have page.json")
            check("Report Visual Count (64 visuals)", total_visuals == 64, f"{total_visuals} visual definitions validated")
        except Exception as e:
            check("pages.json Validation", False, f"Error: {e}")
    else:
        check("pages.json Existence", False, "Missing pages.json")

    # 5. Semantic Model TMDL files
    tmdl_dir = model_dir / "definition" / "tables"
    tmdl_tables = sorted([p.name for p in tmdl_dir.glob("*.tmdl")])
    check("Semantic Model Tables Count (12 tables)", len(tmdl_tables) == 12, f"Tables: {', '.join(tmdl_tables)}")

    for tmdl_name in ["database.tmdl", "model.tmdl", "relationships.tmdl"]:
        tf = model_dir / "definition" / tmdl_name
        check(f"Semantic Model Definition {tmdl_name}", tf.exists() and tf.stat().st_size > 0, f"{tf.stat().st_size if tf.exists() else 0} bytes")

    # 6. Semantic Model Editor Settings (.pbi/editorSettings.json)
    editor_settings_path = model_dir / ".pbi" / "editorSettings.json"
    if editor_settings_path.exists():
        try:
            with open(editor_settings_path, "r", encoding="utf-8") as esf:
                es_data = json.load(esf)
            check("editorSettings.json JSON Parse", True, "Parsed successfully")
            es_version = es_data.get("version")
            check("editorSettings.json Version Field", es_version == "1.0", f"version '{es_version}' (required by DatasetEditorSettings)")
            has_invalid_prop = "useEnhancedDataModeling" in es_data
            check("editorSettings.json Clean Properties", not has_invalid_prop, "Free of deprecated/invalid properties")
        except Exception as e:
            check("editorSettings.json JSON Parse", False, f"Error: {e}")
    else:
        check("editorSettings.json Existence", False, "File missing")

    # 7. All JSON files syntax validation
    all_json_files = list(report_dir.rglob("*.json")) + list(model_dir.rglob("*.json"))
    json_errors = []
    for jf in all_json_files:
        try:
            with open(jf, "r", encoding="utf-8") as jfp:
                json.load(jfp)
        except Exception as err:
            json_errors.append(f"{jf.name}: {err}")
    check("Total JSON Files Validated", len(json_errors) == 0, f"{len(all_json_files)} JSON files successfully parsed")

    # 8. Backup preservation
    backups = [
        base_dir / "CRIC_Analytics_Dashboard_v2.pbip.bak",
        report_dir / "definition.pbir.bak",
        report_dir / ".platform.bak",
        model_dir / ".platform.bak",
        model_dir / ".pbi" / "editorSettings.json.bak",
    ]
    all_backups_present = all(b.exists() for b in backups)
    check("Backups Preserved", all_backups_present, f"{sum(1 for b in backups if b.exists())}/{len(backups)} backups present")

    return results


if __name__ == "__main__":
    pbip = Path(r"c:\CRIC\powerbi\CRIC_Analytics_Dashboard_v2.pbip")
    res = validate_pbip(pbip)
    print("\n================= AUTOMATED PBIP VALIDATION REPORT =================")
    for c in res["checks"]:
        status = "PASS" if c["passed"] else "FAIL"
        print(f"[{status}] {c['name']}: {c['detail']}")
    print("=====================================================================")
    if res["errors"]:
        print(f"\nTOTAL FAILURES: {len(res['errors'])}")
        for e in res["errors"]:
            print(f"  - {e}")
        exit(1)
    else:
        print("\nALL AUTOMATED VALIDATION CHECKS PASSED PERFECTLY (0 ERRORS)")
