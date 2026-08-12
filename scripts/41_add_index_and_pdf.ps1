# 41_add_index_and_pdf.ps1 — insert a real table of contents, then export to PDF.
#
# The index is built by Word rather than written by hand, for one reason: page numbers.
# A hand-authored contents list is wrong the moment a figure reflows, and this document is
# assembled from two builders plus an appended evidence appendix, so pagination is not
# knowable ahead of time. A TOC field asks Word for the numbers at build time.
#
# It also produces PDF bookmarks, so the reader gets a navigation pane rather than 97 pages
# of scrolling.
#
# Runs against the MERGED document, after the appendix has been added — inserting upstream
# would leave the page numbers describing a document that no longer exists.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$src  = Join-Path $root "report\OPEN_THIS_FINAL_MERGED_SUBMISSION.docx"
$pdf  = Join-Path $root "report\OPEN_THIS_FINAL_MERGED_SUBMISSION.pdf"

if (-not (Test-Path $src)) { throw "merged document not found: $src" }

Get-Process WINWORD -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0

try {
    $doc = $word.Documents.Open($src, $false, $false)

    # Remove any TOC this script added on a previous run, so re-running does not stack them.
    while ($doc.TablesOfContents.Count -gt 0) {
        $doc.TablesOfContents.Item(1).Delete()
        Write-Output "  removed an existing table of contents"
    }

    # Insert before the first Heading 1 so the title page stays first.
    $anchor = $null
    foreach ($p in $doc.Paragraphs) {
        if ($p.Style.NameLocal -like "Heading 1*") { $anchor = $p.Range; break }
    }
    if ($null -eq $anchor) { $anchor = $doc.Range(0, 0) }

    $r = $doc.Range($anchor.Start, $anchor.Start)
    $r.InsertParagraphBefore()
    $r.InsertBefore("Contents")
    $r.Style = $doc.Styles.Item("Heading 1")

    $after = $doc.Range($r.End, $r.End)
    $after.InsertParagraphAfter()
    $tocRange = $doc.Range($r.End + 1, $r.End + 1)

    # Headings 1-2 only. Including level 3 on a document this size produces an index longer
    # than some of the sections it points at.
    $toc = $doc.TablesOfContents.Add($tocRange, $true, 1, 2, $false, "", $true, $true)

    $brk = $doc.Range($toc.Range.End, $toc.Range.End)
    $brk.InsertParagraphAfter()
    $brk.InsertBreak(7)          # wdPageBreak — appendix starts on a fresh page

    $doc.TablesOfContents.Item(1).Update()
    $doc.Fields.Update() | Out-Null
    $doc.Repaginate()

    $entries = $doc.TablesOfContents.Item(1).Range.Paragraphs.Count
    $pages   = $doc.ComputeStatistics(2)      # wdStatisticPages

    $doc.Save()

    # 17 = wdExportFormatPDF. CreateBookmarks 1 = from headings, so the PDF gets a nav pane.
    $doc.ExportAsFixedFormat($pdf, 17, $false, 0, 0, 0, 0, 0, $true, $true, 1, $true, $true, $false)

    Write-Output "  contents inserted: $entries entries, headings 1-2"
    Write-Output "  document repaginated: $pages pages"
    Write-Output "  PDF exported with heading bookmarks"

    $doc.Close($false)
}
finally {
    $word.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
}

Get-Item $src, $pdf | Select-Object Name, @{n = 'KB'; e = { [int]($_.Length / 1KB) } }
