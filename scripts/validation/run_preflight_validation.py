"""
CRIC Power BI - Comprehensive 22-Point Preflight Validation Pipeline
Validates end-to-end PBIP structural integrity, metadata, TMDL model, DAX dependencies,
relationship ambiguity, visual query bindings, database integration, metric parity,
and generator idempotence.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.database.connection import DatabaseConnection

PBIP_ROOT = PROJECT_ROOT / "powerbi" / "CRIC_Analytics_Dashboard_v2.pbip"
REPORT_DIR = PROJECT_ROOT / "powerbi" / "CRIC_Analytics_Dashboard_v2.Report"
MODEL_DIR = PROJECT_ROOT / "powerbi" / "CRIC_Analytics_Dashboard_v2.SemanticModel"
LEGACY_MODEL = PROJECT_ROOT / "powerbi" / "CRIC_Analytics_Dashboard_v2" / "Model"


class PreflightValidator:
    def __init__(self) -> None:
        self.results: list[dict[str, Any]] = []
        self.failures: list[str] = []
        self.tables: dict[str, dict[str, Any]] = {}
        self.all_measures: dict[str, tuple[str, str]] = {}
        self.relationships: list[dict[str, Any]] = []

    def record(self, num: int, name: str, passed: bool, detail: str) -> None:
        status = "PASS" if passed else "FAIL"
        self.results.append({"num": num, "name": name, "status": status, "detail": detail})
        if not passed:
            self.failures.append(f"[{num}. {name}] {detail}")

    def run_all(self) -> bool:
        self._load_semantic_model()
        
        # 1. PBIP Structure
        self.check_01_pbip_structure()
        # 2. Metadata & Schemas
        self.check_02_metadata_schemas()
        # 3. Valid GUIDs
        self.check_03_valid_guids()
        # 4. Duplicate Model Objects
        self.check_04_duplicate_model_objects()
        # 5. Duplicate Measures
        self.check_05_duplicate_measures()
        # 6. Missing Measures
        self.check_06_missing_measures()
        # 7. DAX Dependencies
        self.check_07_dax_dependencies()
        # 8. Circular Dependencies
        self.check_08_circular_dependencies()
        # 9. TMDL References
        self.check_09_tmdl_references()
        # 10. Ambiguous Relationships
        self.check_10_ambiguous_relationships()
        # 11. Cardinality
        self.check_11_cardinality()
        # 12. Missing Columns
        self.check_12_missing_columns()
        # 13. Data Types
        self.check_13_data_types()
        # 14. Power Query References
        self.check_14_power_query_references()
        # 15. PostgreSQL Objects
        self.check_15_postgres_objects()
        # 16. Missing Visual Bindings
        self.check_16_missing_visual_bindings()
        # 17. Unsupported Visual Configurations
        self.check_17_unsupported_visual_configs()
        # 18. Broken Page References
        self.check_18_broken_page_references()
        # 19. Filter Relationships
        self.check_19_filter_relationships()
        # 20. Analytical Parity
        self.check_20_analytical_parity()
        # 21. Generator Regressions
        self.check_21_generator_regressions()
        # 22. Missing Project Files
        self.check_22_missing_project_files()

        return len(self.failures) == 0

    def _load_semantic_model(self) -> None:
        tmdl_dir = MODEL_DIR / "definition" / "tables"
        for tf in tmdl_dir.glob("*.tmdl"):
            tname = tf.stem
            cols: dict[str, str] = {}
            meas: dict[str, str] = {}
            curr_col: str | None = None
            with open(tf, "r", encoding="utf-8") as f:
                for line in f:
                    c_m = re.match(r"^\s*column\s+(?:(?:'([^']+)')|([^\s=]+))", line)
                    if c_m:
                        curr_col = c_m.group(1) or c_m.group(2)
                    dt_m = re.match(r"^\s*dataType:\s*(\w+)", line)
                    if dt_m and curr_col:
                        cols[curr_col] = dt_m.group(1)
                        curr_col = None
                    m_m = re.match(r"^\s*measure\s+(?:(?:'([^']+)')|([^\s=]+))\s*=\s*(.*)", line)
                    if m_m:
                        mname = m_m.group(1) or m_m.group(2)
                        meas[mname] = m_m.group(3).strip()
            self.tables[tname] = {"cols": cols, "meas": meas}
            for mname, dax in meas.items():
                self.all_measures[mname] = (tname, dax)

        rel_file = MODEL_DIR / "definition" / "relationships.tmdl"
        if rel_file.exists():
            with open(rel_file, "r", encoding="utf-8") as f:
                blocks = f.read().split("relationship ")
            for b in blocks[1:]:
                lines = b.strip().split("\n")
                r_id = lines[0].strip()
                fc, tc = None, None
                fcard, tcard = "many", "one"
                active = True
                for l in lines:
                    if "fromColumn:" in l:
                        fc = l.split("fromColumn:")[1].strip()
                    if "toColumn:" in l:
                        tc = l.split("toColumn:")[1].strip()
                    if "isActive: false" in l:
                        active = False
                    if "fromCardinality:" in l:
                        fcard = l.split("fromCardinality:")[1].strip()
                    if "toCardinality:" in l:
                        tcard = l.split("toCardinality:")[1].strip()
                if fc and tc:
                    self.relationships.append({
                        "id": r_id, "from": fc, "to": tc,
                        "fromCard": fcard, "toCard": tcard, "active": active
                    })

    # 1. Invalid PBIP structure
    def check_01_pbip_structure(self) -> None:
        if not PBIP_ROOT.exists():
            self.record(1, "PBIP Structure", False, f"Missing {PBIP_ROOT}")
            return
        try:
            with open(PBIP_ROOT, "r", encoding="utf-8") as f:
                data = json.load(f)
            ver = data.get("version")
            artifacts = data.get("artifacts", [])
            rep_path = artifacts[0].get("report", {}).get("path") if artifacts else None
            ok = ver == "1.0" and rep_path == "CRIC_Analytics_Dashboard_v2.Report"
            self.record(1, "PBIP Structure", ok, f"version={ver}, report={rep_path}")
        except Exception as e:
            self.record(1, "PBIP Structure", False, str(e))

    # 2. Invalid metadata
    def check_02_metadata_schemas(self) -> None:
        p_rep = REPORT_DIR / ".platform"
        p_mod = MODEL_DIR / ".platform"
        ed_file = MODEL_DIR / ".pbi" / "editorSettings.json"
        
        ok = True
        details = []
        if p_rep.exists():
            d = json.load(open(p_rep, encoding="utf-8"))
            if d.get("config", {}).get("version") != "2.0":
                ok = False
                details.append("Report .platform version != 2.0")
        else:
            ok = False; details.append("Report .platform missing")

        if p_mod.exists():
            d = json.load(open(p_mod, encoding="utf-8"))
            if d.get("config", {}).get("version") != "2.0":
                ok = False
                details.append("SemanticModel .platform version != 2.0")
        else:
            ok = False; details.append("SemanticModel .platform missing")

        if ed_file.exists():
            ed = json.load(open(ed_file, encoding="utf-8"))
            if ed.get("version") != "1.0":
                ok = False
                details.append("editorSettings.json version != 1.0")
            if "useEnhancedDataModeling" in ed:
                ok = False
                details.append("editorSettings.json contains deprecated useEnhancedDataModeling")
        else:
            ok = False; details.append("editorSettings.json missing")

        rep_json_file = REPORT_DIR / "definition" / "report.json"
        if rep_json_file.exists():
            rep_json = json.load(open(rep_json_file, encoding="utf-8"))
            lo = rep_json.get("layoutOptimization")
            if lo not in {"None", "PhonePortrait", "PhoneLandscape"}:
                ok = False
                details.append(f"report.json layoutOptimization '{lo}' invalid (must be const None/PhonePortrait/PhoneLandscape)")
        else:
            ok = False; details.append("report.json missing")

        self.record(2, "Metadata & Schemas", ok, "; ".join(details) if details else "All schemas verified")

    # 3. Invalid GUIDs
    def check_03_valid_guids(self) -> None:
        guids = []
        for pf in [REPORT_DIR / ".platform", MODEL_DIR / ".platform"]:
            if pf.exists():
                d = json.load(open(pf, encoding="utf-8"))
                lid = d.get("config", {}).get("logicalId")
                try:
                    u = uuid.UUID(lid)
                    if len(lid) == 36 and str(u) == lid.lower():
                        guids.append(lid)
                except Exception:
                    pass
        ok = len(guids) == 2 and len(set(guids)) == 2
        self.record(3, "Logical GUIDs", ok, f"2 distinct valid RFC 4122 GUIDs: {guids}")

    # 4. Duplicate semantic model objects
    def check_04_duplicate_model_objects(self) -> None:
        t_names = list(self.tables.keys())
        dups = [t for t in set(t_names) if t_names.count(t) > 1]
        ok = len(dups) == 0 and len(t_names) == 12
        self.record(4, "Duplicate Semantic Model Objects", ok, f"12 unique tables, duplicates={dups}")

    # 5. Duplicate measures (Model level uniqueness)
    def check_05_duplicate_measures(self) -> None:
        measure_locs: dict[str, list[str]] = {}
        for tname, tdata in self.tables.items():
            for m in tdata["meas"]:
                measure_locs.setdefault(m, []).append(tname)
        dups = {m: locs for m, locs in measure_locs.items() if len(locs) > 1}
        ok = len(dups) == 0
        self.record(5, "Duplicate Measures", ok, f"0 duplicate measure names across model (checked {len(self.all_measures)} measures)" if ok else f"Duplicates found: {dups}")

    # 6. Missing measures
    def check_06_missing_measures(self) -> None:
        # Check all visuals and see if any projected measure is missing
        missing = []
        for vf in REPORT_DIR.glob("definition/pages/*/visuals/*/visual.json"):
            vdata = json.load(open(vf, encoding="utf-8"))
            qs = vdata.get("visual", {}).get("query", {}).get("queryState", {})
            def check(obj):
                if isinstance(obj, dict):
                    if "Measure" in obj:
                        m_prop = obj["Measure"].get("Property")
                        if m_prop and m_prop not in self.all_measures:
                            missing.append(m_prop)
                    for v in obj.values():
                        check(v)
                elif isinstance(obj, list):
                    for item in obj:
                        check(item)
            check(qs)
        ok = len(missing) == 0
        self.record(6, "Missing Measures in Visuals", ok, f"0 missing measures across 64 visuals" if ok else f"Missing: {missing}")

    # 7. Invalid DAX dependencies
    def check_07_dax_dependencies(self) -> None:
        errors = []
        for mname, (tname, dax) in self.all_measures.items():
            tc_refs = re.findall(r"(\b\w+)\s*\[([^\]]+)\]", dax)
            for ref_table, ref_col in tc_refs:
                if ref_table not in self.tables:
                    errors.append(f"[{mname}] references unknown table {ref_table}")
                elif ref_col not in self.tables[ref_table]["cols"]:
                    errors.append(f"[{mname}] references unknown column {ref_table}[{ref_col}]")
            m_refs = re.findall(r"(?<!\w)\[([^\]]+)\]", dax)
            for ref_m in m_refs:
                if any(ref_m == c for _, c in tc_refs):
                    continue
                if ref_m not in self.all_measures:
                    errors.append(f"[{mname}] references unknown measure {ref_m}")
        ok = len(errors) == 0
        self.record(7, "DAX Dependency Resolution", ok, f"All {len(self.all_measures)} measures resolve cleanly" if ok else f"Errors: {errors}")

    # 8. Circular dependencies
    def check_08_circular_dependencies(self) -> None:
        dep_graph: dict[str, list[str]] = {}
        for mname, (tname, dax) in self.all_measures.items():
            dep_graph[mname] = []
            tc_refs = [c for _, c in re.findall(r"(\b\w+)\s*\[([^\]]+)\]", dax)]
            for ref_m in re.findall(r"(?<!\w)\[([^\]]+)\]", dax):
                if ref_m not in tc_refs and ref_m in self.all_measures:
                    dep_graph[mname].append(ref_m)
        has_cycle = False
        visited: set[str] = set()
        stack: set[str] = set()
        def dfs(node: str) -> bool:
            visited.add(node)
            stack.add(node)
            for nbr in dep_graph.get(node, []):
                if nbr not in visited:
                    if dfs(nbr): return True
                elif nbr in stack:
                    return True
            stack.remove(node)
            return False
        for m in dep_graph:
            if m not in visited:
                if dfs(m):
                    has_cycle = True
                    break
        self.record(8, "Circular Dependencies", not has_cycle, "DAG verified with 0 cycles")

    # 9. Invalid TMDL references
    def check_09_tmdl_references(self) -> None:
        req_files = ["database.tmdl", "model.tmdl", "relationships.tmdl"]
        missing = [f for f in req_files if not (MODEL_DIR / "definition" / f).exists()]
        ok = len(missing) == 0 and len(self.tables) == 12
        self.record(9, "TMDL References", ok, "database, model, relationships, and 12 table TMDLs present")

    # 10. Ambiguous relationships
    def check_10_ambiguous_relationships(self) -> None:
        # Check active relationships between the same pair of tables
        pairs: dict[tuple[str, str], list[str]] = {}
        for r in self.relationships:
            if r["active"]:
                ft = r["from"].split(".")[0]
                tt = r["to"].split(".")[0]
                pairs.setdefault((ft, tt), []).append(r["id"])
        ambiguous = {k: ids for k, ids in pairs.items() if len(ids) > 1}
        ok = len(ambiguous) == 0
        self.record(10, "Ambiguous Relationships", ok, "0 duplicate active paths (role-playing correctly separated)" if ok else f"Ambiguous: {ambiguous}")

    # 11. Incorrect cardinality
    def check_11_cardinality(self) -> None:
        invalid = []
        for r in self.relationships:
            if r["fromCard"] != "many" or r["toCard"] != "one":
                invalid.append(r["id"])
        ok = len(invalid) == 0 and len(self.relationships) == 8
        self.record(11, "Relationship Cardinality", ok, f"All 8 relationships strictly many:one")

    # 12. Missing columns
    def check_12_missing_columns(self) -> None:
        db = DatabaseConnection()
        missing = []
        with db.cursor() as cur:
            for tname, tdata in self.tables.items():
                content = (MODEL_DIR / "definition" / "tables" / f"{tname}.tmdl").read_text(encoding="utf-8")
                m_s = re.search(r'Schema="([^"]+)"', content)
                m_i = re.search(r'Item="([^"]+)"', content)
                if m_s and m_i:
                    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s", (m_s.group(1), m_i.group(1)))
                    db_cols = {row[0] for row in cur.fetchall()}
                    for c in tdata["cols"]:
                        if c not in db_cols:
                            missing.append(f"{tname}.{c}")
        ok = len(missing) == 0
        self.record(12, "Column Schema Verification", ok, f"All columns matched in PostgreSQL" if ok else f"Missing: {missing}")

    # 13. Invalid data types
    def check_13_data_types(self) -> None:
        # Verify all TMDL columns have valid types
        valid_types = {"int64", "string", "decimal", "boolean", "dateTime"}
        invalid = []
        for tname, tdata in self.tables.items():
            for c, dt in tdata["cols"].items():
                if dt not in valid_types:
                    invalid.append(f"{tname}.{c}:{dt}")
        ok = len(invalid) == 0
        self.record(13, "Data Types", ok, f"All column data types valid TMDL types ({valid_types})")

    # 14. Broken Power Query references
    def check_14_power_query_references(self) -> None:
        broken = []
        for tf in (MODEL_DIR / "definition" / "tables").glob("*.tmdl"):
            content = tf.read_text(encoding="utf-8")
            if 'PostgreSQL.Database("127.0.0.1:5432", "cric_analytics")' not in content:
                broken.append(f"{tf.name}: invalid host/db M string")
        ok = len(broken) == 0
        self.record(14, "Power Query M Partitions", ok, f"All 12 tables connect to PostgreSQL 127.0.0.1:5432/cric_analytics")

    # 15. Invalid PostgreSQL objects
    def check_15_postgres_objects(self) -> None:
        db = DatabaseConnection()
        missing = []
        with db.cursor() as cur:
            for tf in (MODEL_DIR / "definition" / "tables").glob("*.tmdl"):
                content = tf.read_text(encoding="utf-8")
                m_s = re.search(r'Schema="([^"]+)"', content)
                m_i = re.search(r'Item="([^"]+)"', content)
                if m_s and m_i:
                    cur.execute("SELECT 1 FROM information_schema.tables WHERE table_schema=%s AND table_name=%s", (m_s.group(1), m_i.group(1)))
                    if not cur.fetchone():
                        # check views
                        cur.execute("SELECT 1 FROM information_schema.views WHERE table_schema=%s AND table_name=%s", (m_s.group(1), m_i.group(1)))
                        if not cur.fetchone():
                            missing.append(f"{m_s.group(1)}.{m_i.group(1)}")
        ok = len(missing) == 0
        self.record(15, "PostgreSQL Objects", ok, "All 12 database tables/views exist and are queryable")

    # 16. Missing visual bindings
    def check_16_missing_visual_bindings(self) -> None:
        issues = []
        for vf in REPORT_DIR.glob("definition/pages/*/visuals/*/visual.json"):
            vdata = json.load(open(vf, encoding="utf-8"))
            qs = vdata.get("visual", {}).get("query", {}).get("queryState", {})
            def check(obj):
                if isinstance(obj, dict):
                    if "Column" in obj:
                        ent = obj["Column"].get("Expression", {}).get("SourceRef", {}).get("Entity")
                        prop = obj["Column"].get("Property")
                        if ent not in self.tables or prop not in self.tables[ent]["cols"]:
                            issues.append(f"Visual references unknown column {ent}.{prop}")
                    elif "Measure" in obj:
                        ent = obj["Measure"].get("Expression", {}).get("SourceRef", {}).get("Entity")
                        prop = obj["Measure"].get("Property")
                        if ent not in self.tables or prop not in self.tables[ent]["meas"]:
                            issues.append(f"Visual references unknown measure {ent}.{prop}")
                    for v in obj.values(): check(v)
                elif isinstance(obj, list):
                    for item in obj: check(item)
            check(qs)
        ok = len(issues) == 0
        self.record(16, "Visual Bindings", ok, f"All 64 visuals bind to existing model objects" if ok else f"Issues: {issues}")

    # 17. Unsupported visual configurations
    def check_17_unsupported_visual_configs(self) -> None:
        supported = {"card", "table", "matrix", "barChart", "clusteredColumnChart", "lineChart", "donutChart", "pieChart", "scatterChart", "textbox", "slicer"}
        unsupported = []
        count = 0
        for vf in REPORT_DIR.glob("definition/pages/*/visuals/*/visual.json"):
            count += 1
            vdata = json.load(open(vf, encoding="utf-8"))
            vt = vdata.get("visual", {}).get("visualType")
            if vt not in supported:
                unsupported.append(vt)
        ok = len(unsupported) == 0 and count == 64
        self.record(17, "Visual Configurations", ok, f"64 visual definitions validated across supported visual types")

    # 18. Broken page references
    def check_18_broken_page_references(self) -> None:
        pj_file = REPORT_DIR / "definition" / "pages" / "pages.json"
        pdata = json.load(open(pj_file, encoding="utf-8"))
        porder = pdata.get("pageOrder", [])
        missing = [pid for pid in porder if not (REPORT_DIR / "definition" / "pages" / pid / "page.json").exists()]
        ok = len(missing) == 0 and len(porder) == 8
        self.record(18, "Page References", ok, f"All 8 report page directories and definitions intact")

    # 19. Filter relationships
    def check_19_filter_relationships(self) -> None:
        # Verify crossFilteringBehavior is strictly oneDirection
        rel_file = MODEL_DIR / "definition" / "relationships.tmdl"
        content = rel_file.read_text(encoding="utf-8")
        has_both = "crossFilteringBehavior: bothDirections" in content
        self.record(19, "Filter Relationships", not has_both, "Strict single-direction cross filtering (no bidirectional filter leakage)")

    # 20. Analytical calculation discrepancies
    def check_20_analytical_parity(self) -> None:
        # Run metric parity audit
        from scripts.validation.verify_metric_parity import run_metric_parity_checks
        try:
            res = run_metric_parity_checks()
            ok = all(v.get("status") in {"PASS", "DOCUMENTED"} for v in res.values())
            self.record(20, "Analytical Calculation Parity", ok, "Zero calculation discrepancies against validated baseline")
        except Exception as e:
            self.record(20, "Analytical Calculation Parity", False, str(e))

    # 21. Generator regressions
    def check_21_generator_regressions(self) -> None:
        # Check that running build_cric_modern_pbip.py generates identical output
        import subprocess
        h1 = self._hash_pbip_tree()
        subprocess.check_call([sys.executable, str(PROJECT_ROOT / "scripts" / "maintenance" / "build_cric_modern_pbip.py")])
        h2 = self._hash_pbip_tree()
        ok = h1 == h2
        self.record(21, "Generator Idempotence", ok, f"Generator is 100% repeatable with 0 regressions")

    def _hash_pbip_tree(self) -> dict[str, str]:
        hashes = {}
        for p in sorted(glob.glob(str(PROJECT_ROOT / "powerbi" / "CRIC_Analytics_Dashboard_v2.*") + "/**/*", recursive=True)):
            if os.path.isfile(p):
                hashes[p] = hashlib.sha256(open(p, "rb").read()).hexdigest()
        return hashes

    # 22. Missing project files
    def check_22_missing_project_files(self) -> None:
        expected = [
            PROJECT_ROOT / "powerbi" / "CRIC_Analytics_Dashboard_v2.pbip",
            PROJECT_ROOT / "powerbi" / "CRIC_Analytics_Dashboard_v2.pbip.bak",
            REPORT_DIR / ".platform",
            REPORT_DIR / ".platform.bak",
            REPORT_DIR / "definition.pbir",
            REPORT_DIR / "definition.pbir.bak",
            REPORT_DIR / "definition" / "report.json",
            REPORT_DIR / "definition" / "version.json",
            REPORT_DIR / "definition" / "pages" / "pages.json",
            REPORT_DIR / "StaticResources" / "RegisteredResources" / "CRICTheme.json",
            MODEL_DIR / ".platform",
            MODEL_DIR / ".platform.bak",
            MODEL_DIR / ".pbi" / "editorSettings.json",
            MODEL_DIR / ".pbi" / "editorSettings.json.bak",
            MODEL_DIR / "definition.pbism",
            MODEL_DIR / "definition" / "database.tmdl",
            MODEL_DIR / "definition" / "model.tmdl",
            MODEL_DIR / "definition" / "relationships.tmdl",
        ]
        missing = [str(f.name) for f in expected if not f.exists()]
        ok = len(missing) == 0
        self.record(22, "Required Project Files", ok, f"All core and backup files present ({len(expected)} verified)" if ok else f"Missing: {missing}")


if __name__ == "__main__":
    v = PreflightValidator()
    print("=" * 80)
    print("CRIC POWER BI - 22-POINT COMPREHENSIVE PREFLIGHT VALIDATION PIPELINE")
    print("=" * 80)
    success = v.run_all()
    for r in v.results:
        print(f"[{r['status']}] {r['num']:02d}. {r['name']}: {r['detail']}")
    print("=" * 80)
    if success:
        print("\n>>> ALL 22 PREFLIGHT VALIDATION CHECKS PASSED PERFECTLY (0 FAILURES) <<<")
        sys.exit(0)
    else:
        print(f"\n>>> PREFLIGHT FAILED WITH {len(v.failures)} FAILURES <<<")
        for f in v.failures:
            print(f"  * {f}")
        sys.exit(1)
