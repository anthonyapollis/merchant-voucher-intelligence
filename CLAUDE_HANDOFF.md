# Claude Handoff: Merchant Voucher Intelligence

## Completed deliverable

The final submission is:

`C:\Users\Anthony.DESKTOP-ES5HL78\Downloads\Merchant_Voucher_Intelligence\report\OPEN_THIS_FINAL_MERGED_SUBMISSION.docx`

The complete source-code archive is:

`C:\Users\Anthony.DESKTOP-ES5HL78\Downloads\Merchant_Voucher_Intelligence\Merchant_Voucher_Intelligence_All_Code_FINAL_MERGED_2026-08-11.zip`

It contains 433 project source files, including `scripts/39_unify_health_score.py`, and excludes datasets, downloaded dbt packages, compiled outputs, caches, screenshots, credentials and this conversational handoff note. SHA-256: `F9858DAF32745E5DADEC2E57590D374713C5B06F44B8EA24CBB76E6117A7D8D0`.

It is a 53-page report with 29 embedded visuals. Appendix F begins on page 44 and contains a clean, sequential ten-checkpoint evidence trail:

Use this merged file for submission. The older `OPEN_THIS_FULL_PROCESS_SUBMISSION.docx` remains only as a preserved pre-merge artifact and should not be used. Final DOCX SHA-256: `6B33FE6990A910BFD1C62BC6442F0786A608ABB27E06AF24096D430BD4815D81`.

1. Source ZIP on the analyst PC.
2. ZIP uploaded to Microsoft Fabric OneLake.
3. Exact deployed PySpark ZIP extraction, ABFSS read, lineage and Bronze Delta-write code.
4. All four extracted CSV files verified in OneLake.
5. Completed Fabric Data Factory medallion pipeline execution.
6. Bronze table populations.
7. Silver table populations.
8. Gold reporting table populations.
9. Cross-layer validation gate and row-count reconciliation.
10. Live Fabric SQL reporting query and result.

## Verified live evidence

- OneLake landing ZIP and extracted-file checks use live OneLake DFS service responses.
- The pipeline record uses the live Microsoft Fabric Job Scheduler API.
- Bronze, Silver and Gold counts use the live Fabric Lakehouse SQL endpoint.
- Verified business populations: 25 merchants, 26,500 sales rows, 120,969 voucher-redemption rows and 1,363 support-ticket rows.
- The final DOCX was rendered by Microsoft Word to 53 pages; the corrected base report ends on page 43 and Appendix F runs from pages 44 to 53. The appended process pages were visually checked for clipping, overlap and readability.
- Supporting scripts compile successfully.

## Important presentation note

The added evidence frames are polished captures generated from live Fabric service responses and the exact deployed code. They are deliberately described as service evidence, not recreated Microsoft Fabric portal screenshots. Do not relabel them as portal screenshots unless authenticated browser captures are actually taken.

## Useful next work, only if requested

- Use an authenticated Fabric browser session to replace or supplement the evidence frames with native portal screenshots of OneLake, the notebook cells, pipeline run history, Lakehouse tables and SQL endpoint results.
- Check the final document once in the user's installed Microsoft Word version before submission, especially Compatibility Mode pagination.
- Export the final DOCX to PDF if the recipient requests a fixed-layout submission.
- Review the narrative for role-specific wording and remove any appendix material that exceeds the interview brief.
- Preserve the current final DOCX; create a new version rather than overwriting it.

## Rebuild and QA sources

- `C:\Users\Anthony.DESKTOP-ES5HL78\Documents\Codex\2026-07-24\files-mentioned-by-the-user-recording\work\fabric_doc\render_stage_sequence.py`
- `C:\Users\Anthony.DESKTOP-ES5HL78\Documents\Codex\2026-07-24\files-mentioned-by-the-user-recording\work\fabric_doc\append_complete_process.py`
- `C:\Users\Anthony.DESKTOP-ES5HL78\Documents\Codex\2026-07-24\files-mentioned-by-the-user-recording\work\fabric_doc\render_complete_qa.ps1`
- `C:\Users\Anthony.DESKTOP-ES5HL78\Documents\Codex\2026-07-24\files-mentioned-by-the-user-recording\work\fabric_doc\qa_full_process\Merchant_Voucher_Intelligence_Submission_Full_Process.pdf`
