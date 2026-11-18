from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT = PROJECT_ROOT / "powerbi" / "CRIC_Analytics_Dashboard_v2"
REPORT = PROJECT / "Report"
SECTIONS = REPORT / "sections"


PAGES = [
    ("Executive Overview", [
        ("KPI Cards", "card"),
        ("Season-wise Matches", "clusteredColumnChart"),
        ("Season-wise Wickets", "lineChart"),
        ("Phase Performance", "clusteredColumnChart"),
        ("Top 5 Bowlers", "barChart"),
        ("Top 5 Batters", "barChart"),
    ]),
    ("Bowler Intelligence", [
        ("KPI Cards", "card"),
        ("Top 10 Bowlers", "barChart"),
        ("Economy Comparison", "clusteredColumnChart"),
        ("Strike Rate Comparison", "clusteredColumnChart"),
        ("Wickets vs Economy", "scatterChart"),
        ("Bowler Career Table", "table"),
    ]),
    ("Batter Intelligence", [
        ("KPI Cards", "card"),
        ("Top Run Scorers", "barChart"),
        ("Top Strike-Rate Batters", "barChart"),
        ("Batting Average", "clusteredColumnChart"),
        ("Runs vs Strike Rate", "scatterChart"),
        ("Batter Career Table", "table"),
    ]),
    ("Bowler vs Batter Matchups", [
        ("Matchup KPIs", "card"),
        ("Bowler-Batter Matrix", "matrix"),
        ("Matchup Economy", "clusteredColumnChart"),
        ("Wicket Distribution", "donutChart"),
        ("Effective Combinations", "barChart"),
        ("Matchup Table", "table"),
    ]),
    ("Phase Analysis", [
        ("Phase KPIs", "card"),
        ("Economy by Phase", "clusteredColumnChart"),
        ("Wickets by Phase", "clusteredColumnChart"),
        ("Bowler Phase Table", "table"),
        ("Phase Strike Rates", "lineChart"),
        ("Top Bowlers per Phase", "barChart"),
    ]),
    ("Situation Intelligence", [
        ("Situation KPIs", "card"),
        ("Innings Performance", "clusteredColumnChart"),
        ("Required-Run-Rate Tiers", "clusteredColumnChart"),
        ("Situation Economy", "clusteredColumnChart"),
        ("Situation Wicket Performance", "lineChart"),
        ("Situation Matrix", "matrix"),
    ]),
    ("Wicket Intelligence", [
        ("Wicket KPIs", "card"),
        ("Dismissal Distribution", "donutChart"),
        ("Season Wicket Trends", "lineChart"),
        ("Phase-wise Wickets", "clusteredColumnChart"),
        ("Bowler Wicket Profiles", "barChart"),
        ("Wicket Analysis Table", "table"),
    ]),
    ("Match Strategy and Decision Support", [
        ("Historical Decision Support", "textbox"),
        ("Recommended Shortlist", "table"),
        ("Bowler Career", "table"),
        ("Phase Performance", "clusteredColumnChart"),
        ("Head-to-Head Evidence", "table"),
        ("Situation Evidence", "clusteredColumnChart"),
    ]),
]


def textbox_config(name: str, title: str) -> dict[str, Any]:
    return {
        "name": name,
        "layouts": [{
            "id": 0,
            "position": {"x": 40, "y": 24, "z": 2000, "width": 1200, "height": 52},
        }],
        "singleVisual": {
            "visualType": "textbox",
            "drillFilterOtherVisuals": True,
            "objects": {
                "general": [{
                    "properties": {
                        "paragraphs": [{
                            "textRuns": [{
                                "value": title,
                                "textStyle": {"fontWeight": "bold", "fontSize": "18pt"},
                            }]
                        }]
                    }
                }]
            },
        },
    }


def visual_config(name: str, visual_type: str, title: str, x: int, y: int, width: int, height: int) -> dict[str, Any]:
    return {
        "name": name,
        "layouts": [{
            "id": 0,
            "position": {"x": x, "y": y, "z": 1000, "width": width, "height": height},
        }],
        "singleVisual": {
            "visualType": visual_type,
            "drillFilterOtherVisuals": True,
            "objects": {
                "title": [{
                    "properties": {
                        "show": {"expr": {"Literal": {"Value": "true"}}},
                        "text": {"expr": {"Literal": {"Value": json.dumps(title)}}},
                    }
                }]
            },
        },
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


SECTIONS.mkdir(parents=True, exist_ok=True)
for section in SECTIONS.iterdir():
    if section.is_dir():
        shutil.rmtree(section)

theme_src = PROJECT_ROOT / "powerbi" / "cric_premium_ivory_emerald_theme.json"
theme_dst = PROJECT / "StaticResources" / "RegisteredResources" / "CRICTheme.json"
theme_dst.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(theme_src, theme_dst)

for page_index, (page_name, visuals) in enumerate(PAGES, start=1):
    folder = SECTIONS / f"{page_index:03d}_{page_name.replace(' ', '_')}"
    containers = folder / "visualContainers"
    containers.mkdir(parents=True, exist_ok=True)
    write_json(folder / "section.json", {
        "displayName": page_name,
        "displayOption": 1,
        "height": 720,
        "name": f"ReportSection{page_index}",
        "ordinal": page_index - 1,
        "width": 1280,
    })
    write_json(folder / "config.json", {
        "name": f"ReportSectionConfig{page_index}",
        "layouts": [],
        "filters": [],
        "objects": {},
    })
    write_json(folder / "filters.json", [])

    title_name = f"{page_index:05d}_title"
    title_folder = containers / f"{title_name}_title"
    title_folder.mkdir(parents=True, exist_ok=True)
    title_cfg = textbox_config(title_name, page_name)
    write_json(title_folder / "config.json", title_cfg)
    write_json(title_folder / "filters.json", [])
    write_json(title_folder / "visualContainer.json", {
        "height": title_cfg["layouts"][0]["position"]["height"],
        "width": title_cfg["layouts"][0]["position"]["width"],
        "x": title_cfg["layouts"][0]["position"]["x"],
        "y": title_cfg["layouts"][0]["position"]["y"],
        "z": title_cfg["layouts"][0]["position"]["z"],
    })
    positions = [(40, 88, 390, 260), (450, 88, 390, 260), (860, 88, 380, 260),
                 (40, 370, 390, 260), (450, 370, 390, 260), (860, 370, 380, 260)]
    for visual_index, ((title, visual_type), (x, y, width, height)) in enumerate(zip(visuals, positions), start=1):
        name = f"{page_index:05d}_{visual_index:05d}_{title.replace(' ', '_')}"
        folder_name = f"{name}_{visual_index:04d}"
        container_folder = containers / folder_name
        container_folder.mkdir(parents=True, exist_ok=True)
        cfg = visual_config(name, visual_type, title, x, y, width, height)
        write_json(container_folder / "config.json", cfg)
        write_json(container_folder / "filters.json", [])
        write_json(container_folder / "visualContainer.json", {
            "height": height,
            "width": width,
            "x": x,
            "y": y,
            "z": 1000,
        })

write_json(REPORT / "report.json", {
    "id": 0,
    "layoutOptimization": 0,
    "resourcePackages": [{
        "resourcePackage": {
            "disabled": False,
            "items": [{"name": "CRICTheme", "path": "CRICTheme.json", "type": 100}],
            "name": "RegisteredResources",
            "type": 1,
        }
    }],
})

validation = PROJECT_ROOT / "reports" / "CRIC_PowerBI_Validation_Report.md"
validation.write_text(
    "# CRIC Power BI Validation Report\n\n"
    "## Delivery status\n\n"
    "- A genuine PBIX conversion was not possible offline; the project is delivered as a supported PbixProj-compatible source and PBIT if compilation succeeds.\n"
    "- The prior invalid PBIX was not reused or overwritten.\n"
    "- PostgreSQL credentials are not embedded.\n\n"
    "## Pages\n\n"
    + "\n".join(f"{i}. {name}" for i, (name, _) in enumerate(PAGES, start=1))
    + "\n\n## PostgreSQL source\n\n"
      "Server: `127.0.0.1:5432`\n\nDatabase: `cric_analytics`\n\n"
      "Approved views: all seven frozen analytical views.\n\n"
      "## Remaining verification\n\n"
      "- Open in compatible Power BI Desktop.\n"
      "- Enter PostgreSQL credentials through the secure credential dialog.\n"
      "- Refresh, validate visuals and save as PBIX.\n",
    encoding="utf-8",
)

print(f"Generated {len(PAGES)} report sections under {REPORT}")
