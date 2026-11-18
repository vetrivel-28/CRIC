import json
from pathlib import Path

report_dir = Path("powerbi/CRIC_Analytics_Dashboard_v2.Report")
model_dir = Path("powerbi/CRIC_Analytics_Dashboard_v2.SemanticModel")

# Load TMDL tables
tmdl_tables = {}
for tf in (model_dir / "definition" / "tables").glob("*.tmdl"):
    tname = tf.stem
    cols = set()
    meas = set()
    with open(tf, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("column "):
                c_part = line.replace("column", "").strip()
                cols.add(c_part.strip("'"))
            elif line.startswith("measure "):
                m_part = line.split("=")[0].replace("measure", "").strip()
                meas.add(m_part.strip("'"))
    tmdl_tables[tname] = {"cols": cols, "meas": meas}

# Check pages.json
pages_json = report_dir / "definition" / "pages" / "pages.json"
assert pages_json.exists(), "pages.json missing"
with open(pages_json, "r", encoding="utf-8") as f:
    pj = json.load(f)

page_order = pj.get("pageOrder", [])
print(f"Total pages registered in pages.json: {len(page_order)}")
assert len(page_order) == 8, f"Expected 8 pages, got {len(page_order)}"

valid_visual_types = {
    "card", "table", "matrix", "barChart", "clusteredColumnChart", 
    "lineChart", "donutChart", "pieChart", "scatterChart", "textbox", "slicer"
}

total_visuals = 0
visual_issues = []

for page_idx, pid in enumerate(page_order, start=1):
    pdir = report_dir / "definition" / "pages" / pid
    pfile = pdir / "page.json"
    if not pfile.exists():
        visual_issues.append(f"Page {pid} missing page.json")
        continue
    with open(pfile, "r", encoding="utf-8") as pf:
        pdata = json.load(pf)
    pname = pdata.get("displayName", pid)
    
    vdir = pdir / "visuals"
    vfiles = list(vdir.glob("*/visual.json"))
    print(f"Page {page_idx} [{pname}]: {len(vfiles)} visuals")
    
    positions = []
    for vf in vfiles:
        total_visuals += 1
        with open(vf, "r", encoding="utf-8") as vfp:
            vdata = json.load(vfp)
        vname = vdata.get("name")
        vtype = vdata.get("visual", {}).get("visualType")
        
        if vtype not in valid_visual_types:
            visual_issues.append(f"[{pname}] Visual {vname} has unsupported visualType: {vtype}")
            
        pos = vdata.get("position", {})
        x = pos.get("x", 0)
        y = pos.get("y", 0)
        w = pos.get("width", 0)
        h = pos.get("height", 0)
        
        # Check bounds (1280 x 720 canvas)
        if x < 0 or y < 0 or (x + w) > 1280 or (y + h) > 720:
            visual_issues.append(f"[{pname}] Visual {vname} ({vtype}) bounds overflow: x={x}, y={y}, w={w}, h={h}")
        
        # Check overlapping
        for other_name, (ox, oy, ow, oh) in positions:
            # Check bounding box intersection
            if not (x + w <= ox or ox + ow <= x or y + h <= oy or oy + oh <= y):
                visual_issues.append(f"[{pname}] Visual {vname} overlaps with {other_name}: ({x},{y},{w},{h}) vs ({ox},{oy},{ow},{oh})")
        positions.append((vname, (x, y, w, h)))
        
        # Check queryState
        qs = vdata.get("visual", {}).get("query", {}).get("queryState", {})
        def check_node(obj):
            if isinstance(obj, dict):
                if "Measure" in obj:
                    ent = obj["Measure"].get("Expression", {}).get("SourceRef", {}).get("Entity")
                    prop = obj["Measure"].get("Property")
                    if not ent or ent not in tmdl_tables:
                        visual_issues.append(f"[{pname}] Visual {vname} references unknown Entity {ent}")
                    elif prop not in tmdl_tables[ent]["meas"]:
                        visual_issues.append(f"[{pname}] Visual {vname} references unknown Measure {ent}.[{prop}]")
                elif "Column" in obj:
                    ent = obj["Column"].get("Expression", {}).get("SourceRef", {}).get("Entity")
                    prop = obj["Column"].get("Property")
                    if not ent or ent not in tmdl_tables:
                        visual_issues.append(f"[{pname}] Visual {vname} references unknown Entity {ent}")
                    elif prop not in tmdl_tables[ent]["cols"]:
                        visual_issues.append(f"[{pname}] Visual {vname} references unknown Column {ent}.[{prop}]")
                for v in obj.values():
                    check_node(v)
            elif isinstance(obj, list):
                for item in obj:
                    check_node(item)
        check_node(qs)

print(f"\nTotal Visuals Audited: {total_visuals}")
print(f"Total Visual Issues Found: {len(visual_issues)}")
for issue in visual_issues:
    print("  *", issue)
