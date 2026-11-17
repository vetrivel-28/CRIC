# Phase 2 Pipeline Architecture

## Design principles

1. Preserve the original source data exactly as received.
2. Keep raw, validated, transformed, and derived datasets in separate locations.
3. Allow safe reruns without duplicate publication or accidental dataset overwrite.
4. Record lineage and validation metadata for every stage.
5. Use Python for local orchestration and validation before any HDFS integration.
6. Treat HDFS as an optional target environment, not as a guaranteed runtime in the current machine.

## Proposed stage layout

```text
C:\CRIC\data\
├── raw/                       # staged or copied ingestion inputs (if used)
├── validated/                 # schema-checked, non-source staging data
├── processed/                 # cleaned/standardized intermediate outputs
├── derived/                  # analytical outputs and versioned aggregates
├── merged_cricket_data-.../   # original source package (preserved)
├── wickets_derived_Dataset-.../
├── CRIC_bowler_.../
├── bowler_matchup_situation_.../
└── zookeeper/                # local ZK state only
```

The corresponding HDFS layout should remain logical and consistent with the original project conventions:

```text
/cric/
├── raw/
├── validated/
├── processed/
├── derived/
├── reports/
├── staging/
└── hbase/
```

## Stage flow

### 1. Source discovery

- Scan the project data folders for CSVs.
- Ignore archives and non-source directories unless they are explicitly included.
- Record the dataset inventory and hashes.

### 2. Ingestion preparation

- Validate that each source file exists and is readable.
- Validate required columns for expected file types.
- Record file metadata and file-level validation status.
- Compute the SHA-256 digest for later integrity checks.

### 3. Validation and classification

- `validated`: dataset files that passed schema checks
- `processed`: cleaned or standardized datasets derived from valid inputs
- `derived`: aggregate analytical outputs ready for model or reporting use
- `reports`: documentation, validation summaries, and execution metadata

### 4. Cleaning and transformation

- Enforce the cricket definitions already established in Phase 1.
- Preserve legitimate edge cases and low-sample records.
- Keep extra-wide, zero-legal-ball, and zero-ball rows if they are valid under the documented schema.
- Never silently delete rows from the source package.

### 5. Aggregation

- Compute per-bowler career metrics.
- Generate phase-level summaries.
- Generate matchup and situation summaries.
- Ensure all formulas recalculate from source records, not from stored representative values.

### 6. Validation gates

Each processing stage should validate:

- row counts and file integrity
- duplicate key checks
- required columns and schema integrity
- legal-ball and wicket definitions
- zero-denominator handling
- output row totals vs source totals
- file hashes and manifest checks

### 7. Publication

- Publish only validated outputs.
- Keep a record of which files are published and which are pending or failed.
- Use manifest-driven reruns so the pipeline knows whether a file changed.

## Naming convention

Use explicit, traceable file names such as:

- `deliveries_raw.csv`
- `deliveries_validated.csv`
- `deliveries_cleaned.csv`
- `bowler_career_v1.csv`
- `bowler_phase_v1.csv`
- `bowler_matchup_v2.csv`
- `validation_report_stage_x.csv`
- `pipeline_run_YYYYMMDD_HHMMSS.json`

## Safe rerun model

The ingestion step should maintain a manifest that records:

- relative path
- file size
- SHA-256
- last modified timestamp
- validation status
- HDFS status

A rerun only reprocesses files with changed metadata or failed earlier validation.

## Execution note

The local metadata/validation layer is implemented. Read-only HDFS inventory and integrity comparison have been executed using the explicit Hadoop CLI path. No HDFS synchronization is needed for the verified files, and the Phase 2 Python processing pipeline still reads local CSVs only. Distributed MapReduce remains blocked until a functioning YARN scheduler is configured; see the HDFS integrity and distributed validation reports.
