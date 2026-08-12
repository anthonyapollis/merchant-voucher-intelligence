# Merchant Voucher Intelligence - Code Package

This package contains the project source needed to inspect, explain and rebuild the solution.

## Included

- Python build, validation, Fabric and reporting scripts
- Microsoft Fabric notebooks and Data Factory definitions
- Bronze, Silver and Gold SQL/dbt transformations and tests
- DAX measures
- Power BI PBIP report and semantic-model source definitions
- Dashboard HTML, JavaScript and CSS
- Evidence and DOCX-generation utilities used for the final submission
- Project README and Claude handoff notes

## Excluded

- Raw and generated datasets
- dbt downloaded packages, logs and compiled target files
- Rendered screenshots and QA images
- Generated Office/PDF deliverables
- Cache files and credentials

Fabric authentication is obtained at runtime through Azure CLI or environment variables. No access token or client secret is included in this archive.

The completed report remains at:

`report\OPEN_THIS_FINAL_MERGED_SUBMISSION.docx`
