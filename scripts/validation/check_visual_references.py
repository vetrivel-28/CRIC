import json
from pathlib import Path

model_dir = Path(r"c:\CRIC\powerbi\CRIC_Analytics_Dashboard_v2.SemanticModel")
report_dir = Path(r"c:\CRIC\powerbi\CRIC_Analytics_Dashboard_v2.Report")

tmdl_columns = {}
tmdl_measures = {}

for tf in (model_dir / "definition" / "tables").glob("*.tmdl"):
    table_name = tf.stem
    measures = set()
    columns = set()
    with open(tf, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("measure "):
                m_part = line.split("=")[0].replace("measure", "").strip()
                if m_part.startswith("'") and m_part.endswith("'"):
                    m_name = m_part[1:-1]
                else:
                    m_name = m_part
                measures.add(m_name)
            elif line.startswith("column "):
                c_name = line.replace("column", "").strip()
                columns.add(c_name)
    tmdl_measures[table_name] = measures
    tmdl_columns[table_name] = columns

pages_json = report_dir / "definition" / "pages" / "pages.json"
with open(pages_json, "r", encoding="utf-8") as f:
    pj = json.load(f)

missing_measures = []
missing_columns = []

for pid in pj["pageOrder"]:
    p_dir = report_dir / "definition" / "pages" / pid
    with open(p_dir / "page.json", "r", encoding="utf-8") as pf:
        p_data = json.load(pf)
    p_name = p_data.get("displayName", pid)
    v_files = sorted(list((p_dir / "visuals").glob("*/visual.json")))
    for vf in v_files:
        with open(vf, "r", encoding="utf-8") as vfp:
            v_data = json.load(vfp)
        v_name = v_data.get("name")
        v_type = v_data.get("visual", {}).get("visualType")
        qs = v_data.get("visual", {}).get("query", {}).get("queryState", {})

        def check(obj):
            if isinstance(obj, dict):
                if "Measure" in obj:
                    ent = obj["Measure"].get("Expression", {}).get("SourceRef", {}).get("Entity")
                    prop = obj["Measure"].get("Property")
                    if ent and prop:
                        if prop not in tmdl_measures.get(ent, set()):
                            missing_measures.append((p_name, v_name, v_type, ent, prop))
                elif "Column" in obj:
                    ent = obj["Column"].get("Expression", {}).get("SourceRef", {}).get("Entity")
                    prop = obj["Column"].get("Property")
                    if ent and prop:
                        if prop not in tmdl_columns.get(ent, set()):
                            missing_columns.append((p_name, v_name, v_type, ent, prop))
                for v in obj.values():
                    check(v)
            elif isinstance(obj, list):
                for item in obj:
                    check(item)

        check(qs)

print(f"Missing measures in visuals: {len(missing_measures)}")
for p_name, v_name, v_type, ent, prop in missing_measures:
    print(f"  [MEASURE] [{p_name}] Visual {v_name} ({v_type}): {ent}.[{prop}] NOT FOUND in {ent}.tmdl!")

print(f"\nMissing columns in visuals: {len(missing_columns)}")
for p_name, v_name, v_type, ent, prop in missing_columns:
    print(f"  [COLUMN]  [{p_name}] Visual {v_name} ({v_type}): {ent}.[{prop}] NOT FOUND in {ent}.tmdl!")
