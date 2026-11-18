# CRIC Power BI Metadata Repair & Validation Report

**Date:** 2026-11-18  
**Target:** `powerbi/CRIC_Analytics_Dashboard_v2.pbip`  
**Power BI Desktop Version:** 2.159.1231.0 (26.10), Microsoft Store edition  
**Scope:** Resolution of Power BI Desktop `.platform` metadata GUID deserialization error and `.pbi/editorSettings.json` format/version compatibility error.

---

## 1. Issue Summaries & Root Cause Analysis

### Issue A: Invalid `.platform` Metadata Field
- **Error:**
  ```text
  Cannot read 'C:\CRIC\powerbi\CRIC_Analytics_Dashboard_v2.Report\.platform'. 
  Error converting value "50ce067f3d85c17e" to type 'System.Guid'. Path 'config.logicalId'.
  ```
- **Root Cause:** Truncated 16-character hexadecimal SHA-1 strings (`"50ce067f3d85c17e"` and `"7af9f6c43d8fc900"`) were written into `config.logicalId`. Power BI Desktop's Fabric Git Integration deserializer expects `config.logicalId` to deserialize into a .NET `System.Guid` (a 128-bit RFC 4122 GUID represented as 32 hex digits with 4 hyphens: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`).

### Issue B: Invalid Semantic Model Editor Settings Format
- **Error:**
  ```text
  In file 'C:\CRIC\powerbi\CRIC_Analytics_Dashboard_v2.SemanticModel\.pbi\editorSettings.json' property '$schema' is invalid or has not been found. Attempted to read content in older format. DatasetEditorSettings: Missing version
  ```
- **Root Cause:** `editorSettings.json` contained:
  ```json
  {
    "useEnhancedDataModeling": true,
    "showHiddenFields": true
  }
  ```
  Power BI Desktop checks for `$schema`; when absent, it attempts to parse the content as older `DatasetEditorSettings`. The `DatasetEditorSettings` contract requires a mandatory `"version"` property (canonically `"1.0"`) and does not recognize `"useEnhancedDataModeling"`, resulting in a fatal loading failure.

---

## 2. Repairs Executed

### A. Report Metadata File
- **Path:** `powerbi/CRIC_Analytics_Dashboard_v2.Report/.platform`
- **Backup File:** `powerbi/CRIC_Analytics_Dashboard_v2.Report/.platform.bak`
- **Schema:** `https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json`
- **Original Logical ID:** `"50ce067f3d85c17e"`
- **Repaired Logical ID:** `"03b43c37-6b60-5112-9a73-388e84c29897"` (Valid RFC 4122 UUIDv5 GUID)

### B. Semantic Model Metadata File
- **Path:** `powerbi/CRIC_Analytics_Dashboard_v2.SemanticModel/.platform`
- **Backup File:** `powerbi/CRIC_Analytics_Dashboard_v2.SemanticModel/.platform.bak`
- **Schema:** `https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json`
- **Original Logical ID:** `"7af9f6c43d8fc900"`
- **Repaired Logical ID:** `"6a458244-2f25-5190-9f1b-bdddbea63448"` (Valid RFC 4122 UUIDv5 GUID)

### C. Semantic Model Editor Settings File
- **Path:** `powerbi/CRIC_Analytics_Dashboard_v2.SemanticModel/.pbi/editorSettings.json`
- **Backup File:** `powerbi/CRIC_Analytics_Dashboard_v2.SemanticModel/.pbi/editorSettings.json.bak`
- **Repaired Contents (Conforms to reference templates in `tools/pbip-demo`):**
  ```json
  {
    "version": "1.0",
    "showHiddenFields": true,
    "parallelQueryLoading": true,
    "relationshipImportEnabled": true,
    "shouldNotifyUserOfNameConflictResolution": true
  }
  ```

### D. Generator Script Alignment
- **Path:** `scripts/maintenance/build_cric_modern_pbip.py`
- Updated `guid(text)` to produce RFC 4122 UUIDv5 identifiers for `.platform`.
- Updated `.pbi/editorSettings.json` writer to output the verified `1.0` schema format with all standard flags.

---

## 3. Automated Validation Results

Executed via automated test suite `scripts/validation/validate_pbip.py` and direct .NET `[System.Guid]::Parse`:

| Check / Test | Target | Status | Details |
|---|---|---|---|
| **PBIP File Existence** | `CRIC_Analytics_Dashboard_v2.pbip` | **PASS** | File exists and parses valid JSON |
| **PBIP Artifact Pointer** | PBIP root definition | **PASS** | Resolves to `CRIC_Analytics_Dashboard_v2.Report` |
| **Report `.platform` JSON** | Report root | **PASS** | Valid JSON conforming to Fabric schema 2.0.0 |
| **Report `logicalId` Type** | .NET `System.Guid` Deserializer | **PASS** | Deserialized `03b43c37-6b60-5112-9a73-388e84c29897` |
| **Model `.platform` JSON** | Model root | **PASS** | Valid JSON conforming to Fabric schema 2.0.0 |
| **Model `logicalId` Type** | .NET `System.Guid` Deserializer | **PASS** | Deserialized `6a458244-2f25-5190-9f1b-bdddbea63448` |
| **Artifact ID Uniqueness** | Distinctness check | **PASS** | Report and Model GUIDs are distinct |
| **Dataset Reference** | `definition.pbir` | **PASS** | Resolves to `../CRIC_Analytics_Dashboard_v2.SemanticModel` |
| **Editor Settings JSON** | `.pbi/editorSettings.json` | **PASS** | Successfully parsed JSON |
| **Editor Settings Version** | `editorSettings.json` | **PASS** | Has `"version": "1.0"` (DatasetEditorSettings requirement) |
| **Editor Settings Cleanliness** | `editorSettings.json` | **PASS** | Deprecated `"useEnhancedDataModeling"` removed |
| **Report Pages Count** | `definition/pages/pages.json` | **PASS** | Exactly 8 pages defined |
| **Visual Containers Count** | Page subdirectories | **PASS** | Exactly 64 visuals across 8 pages |
| **Semantic Model Tables** | TMDL table directory | **PASS** | 12 tables present (`dim_dismissal`, `dim_match`, etc.) |
| **TMDL Model Definitions** | TMDL model files | **PASS** | `database.tmdl`, `model.tmdl`, `relationships.tmdl` intact |
| **Total JSON Files** | Report & Model directories | **PASS** | 77 of 77 JSON files parsed successfully |
| **Backup Files Preservation** | PBIP, PBIR, Platform, Editor backups | **PASS** | 5 of 5 backup files preserved intact |

---

## 4. Preservation & Non-Regression Audit

- **Eight Report Pages:** All 8 pages (`Executive Overview`, `Bowler Intelligence`, `Batter Intelligence`, `Bowler vs Batter Matchups`, `Phase Analysis`, `Situation Intelligence`, `Wicket Intelligence`, `Match Strategy and Decision Support`) remain intact.
- **Visuals & Layout:** All 64 visual configurations, query references, Cartesian coordinates, and dimensions remain untouched.
- **Semantic Model & Relationships:** All 8 declared relationships and 12 TMDL table partition definitions remain intact.
- **PostgreSQL Configuration:** Connection strings (`127.0.0.1:5432/cric_analytics`) inside TMDL partitions are unchanged.
- **Backups Preserved:**
  - `powerbi/CRIC_Analytics_Dashboard_v2.pbip.bak`
  - `powerbi/CRIC_Analytics_Dashboard_v2.Report/definition.pbir.bak`
  - `powerbi/CRIC_Analytics_Dashboard_v2.Report/.platform.bak`
  - `powerbi/CRIC_Analytics_Dashboard_v2.SemanticModel/.platform.bak`
  - `powerbi/CRIC_Analytics_Dashboard_v2.SemanticModel/.pbi/editorSettings.json.bak`
- **PBIX Integrity:** No fake `.pbix` file was generated or substituted.

---

## 5. Power BI Desktop Verification Status

- **Host App Identified:** Microsoft Store edition `Microsoft.MicrosoftPowerBIDesktop_8wekyb3d8bbwe` (`PBIDesktopStore.exe` execution alias present in `AppData\Local\Microsoft\WindowsApps`).
- **Interactive Verification Status:** **UNVERIFIED IN DESKTOP GUI**.
  - CLI background execution of Desktop Bridge (`PBIDesktopStore.exe`) spawned process ID 3372, but Store applications require an interactive user desktop session to open their GUI surface.
  - Power BI Desktop GUI open verification remains unverified from this headless environment.
  - No fake PBIX was created, and full compatibility is not claimed based solely on JSON/CLI parsing.
