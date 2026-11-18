from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEGACY_PROJECT = PROJECT_ROOT / "powerbi" / "CRIC_Analytics_Dashboard_v2"
BASE = PROJECT_ROOT / "powerbi"
PBIP = BASE / "CRIC_Analytics_Dashboard_v2.pbip"
REPORT = BASE / "CRIC_Analytics_Dashboard_v2.Report"
MODEL = BASE / "CRIC_Analytics_Dashboard_v2.SemanticModel"


PAGES = [
    ("Executive Overview", [
        ("card", "dim_match", "Total Matches"),
        ("card", "dim_player", "Total Players"),
        ("card", "v_bowler_career_performance", "Total Bowlers"),
        ("card", "v_batter_career_performance", "Total Batters"),
        ("card", "fact_wicket", "Total Wicket Events"),
        ("card", "fact_wicket", "Bowler-Credited Wickets"),
        ("card", "v_bowler_batter_matchups", "Total Matchups"),
        ("clusteredColumnChart", "v_season_bowling_performance", "Season Wickets"),
    ]),
    ("Bowler Intelligence", [
        ("card", "v_bowler_career_performance", "Total Bowlers"),
        ("card", "v_bowler_career_performance", "Total Legal Balls"),
        ("card", "v_bowler_career_performance", "Runs Conceded"),
        ("card", "v_bowler_career_performance", "Credited Wickets"),
        ("card", "v_bowler_career_performance", "Economy Rate"),
        ("card", "v_bowler_career_performance", "Bowling Strike Rate"),
        ("barChart", "v_bowler_career_performance", "Credited Wickets"),
        ("scatterChart", "v_bowler_career_performance", "Economy Rate"),
    ]),
    ("Batter Intelligence", [
        ("card", "v_batter_career_performance", "Total Batters"),
        ("card", "v_batter_career_performance", "Total Runs"),
        ("card", "v_batter_career_performance", "Total Batting Balls"),
        ("card", "v_batter_career_performance", "Batting Average"),
        ("card", "v_batter_career_performance", "Batting Strike Rate"),
        ("barChart", "v_batter_career_performance", "Total Runs"),
        ("scatterChart", "v_batter_career_performance", "Batting Strike Rate"),
        ("table", "v_batter_career_performance", "Batter Career"),
    ]),
    ("Bowler vs Batter Matchups", [
        ("card", "v_bowler_batter_matchups", "Total Matchups"),
        ("card", "v_bowler_batter_matchups", "Matchup Legal Balls"),
        ("card", "v_bowler_batter_matchups", "Matchup Runs"),
        ("card", "v_bowler_batter_matchups", "Matchup Wickets"),
        ("card", "v_bowler_batter_matchups", "Matchup Economy"),
        ("matrix", "v_bowler_batter_matchups", "Bowler-Batter Matrix"),
        ("barChart", "v_bowler_batter_matchups", "Matchup Economy"),
        ("table", "v_bowler_batter_matchups", "Matchup Table"),
    ]),
    ("Phase Analysis", [
        ("card", "v_bowler_phase_performance", "Phase Legal Balls"),
        ("card", "v_bowler_phase_performance", "Phase Runs Conceded"),
        ("card", "v_bowler_phase_performance", "Phase Wickets"),
        ("card", "v_bowler_phase_performance", "Phase Economy"),
        ("clusteredColumnChart", "v_bowler_phase_performance", "Phase Economy"),
        ("clusteredColumnChart", "v_bowler_phase_performance", "Phase Wickets"),
        ("barChart", "v_bowler_phase_performance", "Phase Wickets"),
        ("table", "v_bowler_phase_performance", "Phase Table"),
    ]),
    ("Situation Intelligence", [
        ("card", "v_bowler_situation_performance", "Situation Records"),
        ("card", "v_bowler_situation_performance", "Situation Legal Balls"),
        ("card", "v_bowler_situation_performance", "Situation Runs Conceded"),
        ("card", "v_bowler_situation_performance", "Situation Wickets"),
        ("card", "v_bowler_situation_performance", "Situation Economy"),
        ("clusteredColumnChart", "v_bowler_situation_performance", "Situation Economy"),
        ("lineChart", "v_bowler_situation_performance", "Situation Wickets"),
        ("matrix", "v_bowler_situation_performance", "Situation Matrix"),
    ]),
    ("Wicket Intelligence", [
        ("card", "fact_wicket", "Total Wicket Events"),
        ("card", "fact_wicket", "Bowler-Credited Wickets"),
        ("card", "fact_wicket", "Non-Bowler-Credited Dismissals"),
        ("card", "v_wicket_profiles", "Profile Credited Wickets"),
        ("donutChart", "fact_wicket", "Total Wicket Events"),
        ("lineChart", "v_season_bowling_performance", "Season Wickets"),
        ("clusteredColumnChart", "fact_wicket", "Bowler-Credited Wickets"),
        ("table", "v_wicket_profiles", "Wicket Profile Table"),
    ]),
    ("Match Strategy and Decision Support", [
        ("textbox", "", "Historical decision support - not live recommendations"),
        ("table", "v_bowler_career_performance", "Recommended Shortlist"),
        ("table", "v_bowler_career_performance", "Bowler Career"),
        ("clusteredColumnChart", "v_bowler_phase_performance", "Phase Performance"),
        ("table", "v_bowler_batter_matchups", "Head-to-Head Evidence"),
        ("table", "v_bowler_situation_performance", "Situation Evidence"),
        ("card", "v_bowler_batter_matchups", "Matchup Legal Balls"),
        ("clusteredColumnChart", "v_bowler_situation_performance", "Situation Economy"),
    ]),
]


def uid(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def guid(text: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, text))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def measure_field(entity: str, measure: str) -> dict[str, Any]:
    return {
        "Measure": {
            "Expression": {"SourceRef": {"Entity": entity}},
            "Property": measure,
        }
    }


def column_field(entity: str, property_name: str) -> dict[str, Any]:
    return {
        "Column": {
            "Expression": {"SourceRef": {"Entity": entity}},
            "Property": property_name,
        }
    }


def projection(field: dict[str, Any], query_ref: str, active: bool = True) -> dict[str, Any]:
    return {"field": field, "queryRef": query_ref, "active": active}


def measure_visual(entity: str, measure: str, visual_type: str, name: str) -> dict[str, Any]:
    field = measure_field(entity, measure)
    query_state: dict[str, Any] = {}
    if visual_type == "card":
        query_state = {"Values": {"projections": [projection(field, f"{entity}.{measure}")]}}
    elif visual_type in {"donutChart", "pieChart"}:
        query_state = {
            "Category": {"projections": [projection(column_field("fact_wicket", "kind"), "fact_wicket.kind")]},
            "Y": {"projections": [projection(measure_field("fact_wicket", "Total Wicket Events"), "fact_wicket.Total Wicket Events")]},
        }
    elif visual_type == "table":
        if entity == "v_batter_career_performance":
            query_state = {
                "Values": {
                    "projections": [
                        projection(column_field(entity, "batter_name"), f"{entity}.batter_name"),
                        projection(measure_field(entity, "Total Runs"), f"{entity}.Total Runs"),
                        projection(measure_field(entity, "Total Batting Balls"), f"{entity}.Total Batting Balls"),
                        projection(measure_field(entity, "Batting Average"), f"{entity}.Batting Average"),
                        projection(measure_field(entity, "Batting Strike Rate"), f"{entity}.Batting Strike Rate"),
                    ]
                }
            }
        elif entity == "v_bowler_batter_matchups":
            query_state = {
                "Values": {
                    "projections": [
                        projection(column_field(entity, "bowler_name"), f"{entity}.bowler_name"),
                        projection(column_field(entity, "batter_name"), f"{entity}.batter_name"),
                        projection(measure_field(entity, "Matchup Legal Balls"), f"{entity}.Matchup Legal Balls"),
                        projection(measure_field(entity, "Matchup Runs"), f"{entity}.Matchup Runs"),
                        projection(measure_field(entity, "Matchup Wickets"), f"{entity}.Matchup Wickets"),
                        projection(measure_field(entity, "Matchup Economy"), f"{entity}.Matchup Economy"),
                        projection(column_field(entity, "sample_size_flag"), f"{entity}.sample_size_flag"),
                    ]
                }
            }
        elif entity == "v_bowler_phase_performance":
            query_state = {
                "Values": {
                    "projections": [
                        projection(column_field(entity, "bowler_name"), f"{entity}.bowler_name"),
                        projection(column_field(entity, "match_phase"), f"{entity}.match_phase"),
                        projection(measure_field(entity, "Phase Legal Balls"), f"{entity}.Phase Legal Balls"),
                        projection(measure_field(entity, "Phase Runs Conceded"), f"{entity}.Phase Runs Conceded"),
                        projection(measure_field(entity, "Phase Wickets"), f"{entity}.Phase Wickets"),
                        projection(measure_field(entity, "Phase Economy"), f"{entity}.Phase Economy"),
                    ]
                }
            }
        elif entity == "v_wicket_profiles":
            query_state = {
                "Values": {
                    "projections": [
                        projection(column_field(entity, "bowler_name"), f"{entity}.bowler_name"),
                        projection(measure_field(entity, "Profile Total Wickets"), f"{entity}.Profile Total Wickets"),
                        projection(measure_field(entity, "Profile Credited Wickets"), f"{entity}.Profile Credited Wickets"),
                        projection(column_field(entity, "bowled"), f"{entity}.bowled"),
                        projection(column_field(entity, "caught"), f"{entity}.caught"),
                        projection(column_field(entity, "lbw"), f"{entity}.lbw"),
                        projection(column_field(entity, "pct_bowled_or_lbw"), f"{entity}.pct_bowled_or_lbw"),
                    ]
                }
            }
        elif entity == "v_bowler_career_performance":
            query_state = {
                "Values": {
                    "projections": [
                        projection(column_field(entity, "bowler_name"), f"{entity}.bowler_name"),
                        projection(column_field(entity, "country"), f"{entity}.country"),
                        projection(column_field(entity, "bowling_category"), f"{entity}.bowling_category"),
                        projection(measure_field(entity, "Total Legal Balls"), f"{entity}.Total Legal Balls"),
                        projection(measure_field(entity, "Credited Wickets"), f"{entity}.Credited Wickets"),
                        projection(measure_field(entity, "Economy Rate"), f"{entity}.Economy Rate"),
                        projection(measure_field(entity, "Bowling Strike Rate"), f"{entity}.Bowling Strike Rate"),
                    ]
                }
            }
        elif entity == "v_bowler_situation_performance":
            query_state = {
                "Values": {
                    "projections": [
                        projection(column_field(entity, "bowler_name"), f"{entity}.bowler_name"),
                        projection(column_field(entity, "situation_type"), f"{entity}.situation_type"),
                        projection(column_field(entity, "situation_value"), f"{entity}.situation_value"),
                        projection(measure_field(entity, "Situation Legal Balls"), f"{entity}.Situation Legal Balls"),
                        projection(measure_field(entity, "Situation Wickets"), f"{entity}.Situation Wickets"),
                        projection(measure_field(entity, "Situation Economy"), f"{entity}.Situation Economy"),
                    ]
                }
            }
        else:
            query_state = {"Values": {"projections": [projection(field, f"{entity}.{measure}")]}}
    elif visual_type == "matrix":
        if entity == "v_bowler_batter_matchups":
            query_state = {
                "Rows": {"projections": [projection(column_field(entity, "bowler_name"), f"{entity}.bowler_name")]},
                "Columns": {"projections": [projection(column_field(entity, "batter_name"), f"{entity}.batter_name")]},
                "Values": {"projections": [projection(measure_field(entity, "Matchup Economy"), f"{entity}.Matchup Economy")]},
            }
        elif entity == "v_bowler_situation_performance":
            query_state = {
                "Rows": {"projections": [projection(column_field(entity, "situation_type"), f"{entity}.situation_type")]},
                "Columns": {"projections": [projection(column_field(entity, "situation_value"), f"{entity}.situation_value")]},
                "Values": {"projections": [projection(measure_field(entity, "Situation Economy"), f"{entity}.Situation Economy")]},
            }
        else:
            query_state = {"Values": {"projections": [projection(field, f"{entity}.{measure}")]}}
    elif visual_type == "slicer":
        query_state = {"Values": {"projections": [projection(column_field("dim_match", "season"), "dim_match.season")]}}
    elif visual_type == "scatterChart":
        if entity == "v_batter_career_performance":
            query_state = {
                "Category": {"projections": [projection(column_field(entity, "batter_name"), f"{entity}.batter_name")]},
                "X": {"projections": [projection(measure_field(entity, "Batting Strike Rate"), f"{entity}.Batting Strike Rate")]},
                "Y": {"projections": [projection(measure_field(entity, "Total Runs"), f"{entity}.Total Runs")]},
            }
        else:
            category_entity = "v_bowler_career_performance"
            query_state = {
                "Category": {"projections": [projection(column_field(category_entity, "bowler_name"), f"{category_entity}.bowler_name")]},
                "X": {"projections": [projection(measure_field(category_entity, "Economy Rate"), f"{category_entity}.Economy Rate")]},
                "Y": {"projections": [projection(measure_field(category_entity, "Credited Wickets"), f"{category_entity}.Credited Wickets")]},
            }
    else:
        category_property = "season" if entity == "v_season_bowling_performance" else "match_phase"
        measure_to_project = measure
        if entity == "fact_wicket":
            category_property = "over_phase"
        elif entity == "v_bowler_situation_performance":
            category_property = "situation_value"
        elif entity == "v_bowler_career_performance":
            category_property = "bowler_name"
        elif entity == "v_batter_career_performance":
            category_property = "batter_name"
        elif entity == "v_bowler_batter_matchups":
            category_property = "bowler_name"
        elif entity == "v_bowler_phase_performance":
            category_property = "match_phase"
            if measure == "Phase Performance":
                measure_to_project = "Phase Economy"
        elif entity == "v_wicket_profiles":
            category_property = "bowler_name"
        query_state = {
            "Category": {"projections": [projection(column_field(entity, category_property), f"{entity}.{category_property}")]},
            "Y": {"projections": [projection(measure_field(entity, measure_to_project), f"{entity}.{measure_to_project}")]},
        }

    visual: dict[str, Any] = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.0.0/schema.json",
        "name": name,
        "visual": {
            "visualType": visual_type,
            "query": {"queryState": query_state},
            "drillFilterOtherVisuals": True,
        },
    }
    return visual


def textbox_visual(name: str, text: str) -> dict[str, Any]:
    return {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.0.0/schema.json",
        "name": name,
        "visual": {
            "visualType": "textbox",
            "objects": {
                "general": [{
                    "properties": {
                        "paragraphs": [{
                            "textRuns": [{"value": text, "textStyle": {"fontWeight": "bold", "fontFamily": "Segoe (Bold)", "fontSize": "18pt", "color": "#075B40"}}]
                        }]
                    }
                }]
            },
            "drillFilterOtherVisuals": True,
        },
    }


def validate_authoritative_tmdl(legacy_model_dir: Path) -> dict[str, dict[str, set[str]]]:
    import re
    tables_dir = legacy_model_dir / "tables"
    registry: dict[str, dict[str, set[str]]] = {}
    measure_locations: dict[str, list[str]] = {}
    
    for tf in sorted(tables_dir.glob("*.tmdl")):
        tname = tf.stem
        cols: set[str] = set()
        meas: set[str] = set()
        with open(tf, "r", encoding="utf-8") as f:
            for line in f:
                c_match = re.match(r"^\s*column\s+(?:(?:'([^']+)')|([^\s=]+))", line)
                if c_match:
                    cols.add(c_match.group(1) or c_match.group(2))
                m_match = re.match(r"^\s*measure\s+(?:(?:'([^']+)')|([^\s=]+))\s*=", line)
                if m_match:
                    mname = m_match.group(1) or m_match.group(2)
                    meas.add(mname)
                    measure_locations.setdefault(mname, []).append(tname)
        registry[tname] = {"columns": cols, "measures": meas}
    
    # Strictly reject duplicate measure names across the model (PFE_TM_OBJECT_NAME_ALREADY_EXISTS prevention)
    duplicate_measures = {m: locs for m, locs in measure_locations.items() if len(locs) > 1}
    if duplicate_measures:
        raise ValueError(f"CRITICAL: Duplicate measure names detected across semantic model: {duplicate_measures}")
    
    # Verify expected tables count
    if len(registry) != 12:
        raise ValueError(f"Expected 12 semantic model tables, found {len(registry)}: {list(registry.keys())}")
        
    return registry


# Authoritative preflight validation before recreating directories
registry = validate_authoritative_tmdl(LEGACY_PROJECT / "Model")

# Verify all visuals in PAGES bind to valid authoritative entities and measures
for page_name, visuals in PAGES:
    for vtype, entity, metric in visuals:
        if vtype == "textbox":
            continue
        if entity not in registry:
            raise ValueError(f"Visual in '{page_name}' references unknown entity '{entity}'")
        if vtype != "slicer" and metric not in registry[entity]["measures"]:
            raise ValueError(f"Visual in '{page_name}' references unknown measure '{entity}.[{metric}]'")

# Recreate modern PBIP report and semantic-model folders.
for folder in (REPORT, MODEL):
    if folder.exists():
        shutil.rmtree(folder)

(REPORT / "definition" / "pages").mkdir(parents=True)
(REPORT / "StaticResources" / "RegisteredResources").mkdir(parents=True)
(MODEL / "definition" / "tables").mkdir(parents=True)
(MODEL / ".pbi").mkdir(parents=True)

shutil.copy2(PROJECT_ROOT / "powerbi" / "cric_premium_ivory_emerald_theme.json",
             REPORT / "StaticResources" / "RegisteredResources" / "CRICTheme.json")

write_json(PBIP, {
    "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
    "version": "1.0",
    "artifacts": [{"report": {"path": REPORT.name}}],
    "settings": {"enableAutoRecovery": True},
})
write_json(REPORT / ".platform", {
    "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
    "metadata": {"type": "Report", "displayName": "CRIC Analytics Dashboard v2"},
    "config": {"version": "2.0", "logicalId": guid(f"{PBIP.stem}.Report")},
})
write_json(REPORT / "definition.pbir", {
    "version": "4.0",
    "datasetReference": {"byPath": {"path": "../" + MODEL.name}},
})
write_json(MODEL / ".platform", {
    "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
    "metadata": {"type": "SemanticModel", "displayName": "CRIC Analytics Semantic Model"},
    "config": {"version": "2.0", "logicalId": guid(f"{PBIP.stem}.SemanticModel")},
})
write_json(MODEL / "definition.pbism", {"version": "4.1", "settings": {"qnaEnabled": True}})
write_json(MODEL / ".pbi" / "editorSettings.json", {
    "version": "1.0",
    "showHiddenFields": True,
    "parallelQueryLoading": True,
    "relationshipImportEnabled": True,
    "shouldNotifyUserOfNameConflictResolution": True,
})

# Preserve historical audit backups reflecting pre-repair metadata state
write_json(PBIP.with_suffix(".pbip.bak"), {
    "version": "1.0",
    "artifacts": [{"report": {"path": REPORT.name}}, {"semanticModel": {"path": MODEL.name}}],
    "settings": {"enableAutoRecovery": True},
})
write_json(REPORT / "definition.pbir.bak", {
    "version": "4.0",
    "datasetReference": {"byPath": {"path": "../CRIC_Analytics_Dashboard_v2"}},
})
write_json(REPORT / ".platform.bak", {
    "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
    "metadata": {"type": "Report", "displayName": "CRIC Analytics Dashboard v2"},
    "config": {"version": "2.0", "logicalId": "50ce067f3d85c17e"},
})
write_json(MODEL / ".platform.bak", {
    "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
    "metadata": {"type": "SemanticModel", "displayName": "CRIC Analytics Semantic Model"},
    "config": {"version": "2.0", "logicalId": "a1b2c3d4e5f60718"},
})
write_json(MODEL / ".pbi" / "editorSettings.json.bak", {
    "showHiddenFields": True,
    "parallelQueryLoading": True,
    "relationshipImportEnabled": True,
    "useEnhancedDataModeling": True,
})

for source_name in ("database.tmdl", "model.tmdl", "relationships.tmdl", "expressions.tmdl"):
    source = LEGACY_PROJECT / "Model" / source_name
    if source.exists():
        shutil.copy2(source, MODEL / "definition" / source_name)
for source in (LEGACY_PROJECT / "Model" / "tables").glob("*.tmdl"):
    shutil.copy2(source, MODEL / "definition" / "tables" / source.name)

write_json(REPORT / "definition" / "version.json", {
    "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json",
    "version": "2.0.0",
})
write_json(REPORT / "definition" / "report.json", {
    "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/1.3.0/schema.json",
    "themeCollection": {
        "customTheme": {"name": "CRICTheme.json", "reportVersionAtImport": "5.64", "type": "RegisteredResources"}
    },
    "layoutOptimization": "None",
    "resourcePackages": [{
        "name": "RegisteredResources",
        "type": "RegisteredResources",
        "items": [{"name": "CRICTheme.json", "path": "CRICTheme.json", "type": "CustomTheme"}],
    }],
    "settings": {
        "useStylableVisualContainerHeader": True,
        "exportDataMode": "AllowSummarized",
        "defaultDrillFilterOtherVisuals": True,
    },
})

page_ids: list[str] = []
for page_index, (page_name, visuals) in enumerate(PAGES, start=1):
    page_id = uid(f"page-{page_index}-{page_name}")
    page_ids.append(page_id)
    page_dir = REPORT / "definition" / "pages" / page_id
    visual_dir = page_dir / "visuals"
    visual_dir.mkdir(parents=True)
    write_json(page_dir / "page.json", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/1.4.0/schema.json",
        "name": page_id,
        "displayName": page_name,
        "displayOption": "FitToPage",
        "height": 720,
        "width": 1280,
        "filterConfig": {"filters": [], "filterSortOrder": "Custom"},
    })

    positions = [
        (30, 70, 390, 100), (430, 70, 390, 100), (830, 70, 390, 100),
        (30, 190, 390, 230), (430, 190, 390, 230), (830, 190, 390, 230),
        (30, 440, 390, 230), (430, 440, 390, 230), (830, 440, 390, 230),
    ]
    for visual_index, (visual_type, entity, measure) in enumerate(visuals):
        visual_id = uid(f"{page_id}-{visual_index}-{measure}")
        visual = textbox_visual(visual_id, page_name) if visual_type == "textbox" else measure_visual(entity, measure, visual_type, visual_id)
        x, y, width, height = positions[visual_index]
        visual["position"] = {"x": x, "y": y, "z": 1000 + visual_index * 100, "height": height, "width": width, "tabOrder": visual_index}
        write_json(visual_dir / visual_id / "visual.json", visual)

write_json(REPORT / "definition" / "pages" / "pages.json", {
    "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json",
    "pageOrder": page_ids,
    "activePageName": page_ids[0],
})

# Validation report is managed independently and preserved.
print(f"Generated modern PBIP with {len(PAGES)} pages")
