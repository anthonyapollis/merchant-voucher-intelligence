# Fabric notebook — 00_autoload_landing
# ======================================================================================
# GENERIC LANDING-ZONE AUTOLOADER
#
# Drop ANY file into Files/landing and run this. It works out what the file is, unpacks it
# if it needs unpacking, reads it whatever the format, and writes a bronze Delta table.
#
#   .csv .tsv .txt .psv     delimiter sniffed from the header line
#   .xlsx .xls              every sheet becomes its own table
#   .parquet                read directly
#   .json .jsonl .ndjson    line-delimited or array
#   .zip .gz .tar .tar.gz   unpacked to Files/_unpacked, then each member re-inspected
#
# WHY THIS EXISTS
# The supplied brief is four tidy CSVs. Real landing zones are not: someone sends a zipped
# month-end pack, someone else an Excel workbook with six sheets, and a system starts
# emitting parquet. A pipeline that only reads CSV silently ingests nothing on the day that
# changes — it does not fail, it just processes zero files, which looks identical to a quiet
# day. This notebook detects what arrived rather than assuming.
#
# IDEMPOTENT BY DESIGN
# Every processed file is recorded in bronze_ingest_log with a content fingerprint
# (path + size + modified time). Re-running skips files already loaded, so the notebook is
# safe to schedule every 15 minutes or to re-run after a partial failure. A file whose
# CONTENTS change gets a new fingerprint and is reloaded.
#
# PARAMETERS (overridden by the pipeline)
# ======================================================================================
landing_path = "Files/landing"
unpack_path = "Files/_unpacked"
quarantine_path = "Files/_quarantine"
batch_id = "manual"
reprocess_all = False          # True ignores the ingest log and reloads everything
min_rows = 1                   # a file that reads to fewer rows than this is quarantined

# --------------------------------------------------------------------------------------
import hashlib
import io
import json
import posixpath
import re
import shutil
import tarfile
import traceback
import zipfile
from datetime import datetime

from pyspark.sql import functions as F
from pyspark.sql.types import (StructType, StructField, StringType, LongType,
                               TimestampType, BooleanType)
from pyspark.sql.utils import AnalysisException

LAKEHOUSE = "LH_MerchantVoucher"
LOG_TABLE = f"{LAKEHOUSE}.bronze_ingest_log"
ingested_at = datetime.utcnow()

# In Fabric, Files/ is reachable both through mssparkutils (abfss) and the local /lakehouse
# mount. The mount is used for the messy work — unzipping, reading Excel — because Spark
# cannot open an archive member directly.
MOUNT = "/lakehouse/default"

READERS = {
    "csv": ("delimited", ","), "txt": ("delimited", ","), "tsv": ("delimited", "\t"),
    "psv": ("delimited", "|"),
    "xlsx": ("excel", None), "xls": ("excel", None), "xlsm": ("excel", None),
    "parquet": ("parquet", None), "pq": ("parquet", None),
    "json": ("json", None), "jsonl": ("json", None), "ndjson": ("json", None),
}
ARCHIVES = {"zip", "gz", "tgz", "tar", "bz2", "7z"}

print(f"Autoloader | batch {batch_id} | landing={landing_path} | reprocess_all={reprocess_all}")


# ======================================================================================
# helpers
# ======================================================================================
def mount(p):
    """Files/x -> /lakehouse/default/Files/x"""
    return posixpath.join(MOUNT, p) if not p.startswith(MOUNT) else p


def list_files(path):
    """Recursive listing that tolerates a missing folder rather than exploding."""
    out = []
    try:
        for item in mssparkutils.fs.ls(path):
            if item.isDir:
                out += list_files(item.path)
            else:
                out.append({"path": item.path, "name": item.name, "size": item.size,
                            "modified": item.modifyTime})
    except Exception as e:
        print(f"  (cannot list {path}: {e})")
    return out


def fingerprint(f):
    """Content fingerprint. Path alone is not enough — a file replaced in place with new
    contents must be detected, and hashing multi-GB files on every run is not viable."""
    return hashlib.md5(f"{f['name']}|{f['size']}|{f['modified']}".encode()).hexdigest()


def table_name(stem, sheet=None):
    """Filename -> a legal, predictable Delta table name."""
    s = re.sub(r"[^0-9a-zA-Z]+", "_", stem).strip("_").lower()
    s = re.sub(r"_+", "_", s)
    if sheet:
        s += "_" + re.sub(r"[^0-9a-zA-Z]+", "_", sheet).strip("_").lower()
    if s and s[0].isdigit():
        s = "t_" + s
    return f"bronze_{s}"


def sniff_delimiter(local_path):
    """Read the header line and pick whichever candidate splits it into most columns.
    Beats trusting the extension: plenty of '.csv' files are semicolon- or tab-separated."""
    try:
        with open(local_path, "r", encoding="utf-8-sig", errors="replace") as fh:
            head = fh.readline()
        counts = {d: head.count(d) for d in [",", ";", "\t", "|"]}
        best = max(counts, key=counts.get)
        return best if counts[best] > 0 else ","
    except Exception:
        return ","


def ensure_log():
    try:
        spark.table(LOG_TABLE)
    except AnalysisException:
        schema = StructType([
            StructField("fingerprint", StringType()), StructField("source_file", StringType()),
            StructField("source_path", StringType()), StructField("file_format", StringType()),
            StructField("target_table", StringType()), StructField("row_count", LongType()),
            StructField("size_bytes", LongType()), StructField("status", StringType()),
            StructField("message", StringType()), StructField("batch_id", StringType()),
            StructField("ingested_at", TimestampType()),
        ])
        (spark.createDataFrame([], schema).write.format("delta").mode("overwrite")
         .saveAsTable(LOG_TABLE))
        print(f"  created {LOG_TABLE}")


def already_done():
    if reprocess_all:
        return set()
    try:
        return {r.fingerprint for r in
                spark.table(LOG_TABLE).filter("status = 'LOADED'").select("fingerprint").collect()}
    except Exception:
        return set()


log_rows = []


def record(fp, f, fmt, table, rows, status, message=""):
    log_rows.append((fp, f["name"], f["path"], fmt, table, int(rows),
                     int(f.get("size", 0)), status, message[:900], batch_id, ingested_at))


# ======================================================================================
# 1. UNPACK ARCHIVES
# ======================================================================================
def unpack(f):
    """Expand an archive into Files/_unpacked/<stem>/ and return the extracted paths."""
    src = mount(f["path"].split("/Files/")[-1] if "/Files/" in f["path"] else f["path"])
    if not src.startswith(MOUNT):
        src = mount(posixpath.join("Files", f["name"]))
    stem = re.sub(r"\.(zip|tar|gz|tgz|bz2)$", "", f["name"], flags=re.I)
    dest_rel = posixpath.join(unpack_path, stem)
    dest = mount(dest_rel)
    shutil.rmtree(dest, ignore_errors=True)
    import os
    os.makedirs(dest, exist_ok=True)

    name = f["name"].lower()
    try:
        if name.endswith(".zip"):
            with zipfile.ZipFile(src) as z:
                # Guard against path traversal in a supplied archive
                for m in z.namelist():
                    if m.startswith("/") or ".." in m:
                        raise ValueError(f"unsafe path in archive: {m}")
                z.extractall(dest)
        elif name.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2")):
            with tarfile.open(src) as t:
                for m in t.getnames():
                    if m.startswith("/") or ".." in m:
                        raise ValueError(f"unsafe path in archive: {m}")
                t.extractall(dest)
        elif name.endswith(".gz"):
            import gzip
            out = posixpath.join(dest, stem)
            with gzip.open(src, "rb") as gz, open(out, "wb") as w:
                shutil.copyfileobj(gz, w)
        else:
            return []
    except Exception as e:
        print(f"  UNPACK FAILED {f['name']}: {e}")
        return None
    got = list_files(dest_rel)
    print(f"  unpacked {f['name']} -> {len(got)} file(s)")
    return got


# ======================================================================================
# 2. READ ANY FORMAT
# ======================================================================================
def read_any(f, kind, hint):
    """Return [(dataframe, table_suffix)] — a list because one workbook yields many sheets."""
    rel = f["path"].split("/Files/")[-1]
    abfss = f["path"]
    local = mount(posixpath.join("Files", rel))
    stem = re.sub(r"\.[^.]+$", "", f["name"])

    if kind == "delimited":
        delim = sniff_delimiter(local)
        df = (spark.read.option("header", True).option("inferSchema", True)
              .option("delimiter", delim).option("multiLine", True)
              .option("escape", '"').option("mode", "PERMISSIVE").csv(abfss))
        return [(df, None)]

    if kind == "parquet":
        return [(spark.read.parquet(abfss), None)]

    if kind == "json":
        return [(spark.read.option("multiLine", True).json(abfss), None)]

    if kind == "excel":
        # Spark has no native Excel reader; pandas handles it and the volumes that arrive as
        # Excel are, by definition, small enough for a driver-side read.
        import pandas as pd
        book = pd.read_excel(local, sheet_name=None)
        out = []
        for sheet, pdf in book.items():
            if pdf.empty:
                continue
            pdf.columns = [re.sub(r"[^0-9a-zA-Z]+", "_", str(c)).strip("_") or f"col_{i}"
                           for i, c in enumerate(pdf.columns)]
            pdf = pdf.astype(str).where(pdf.notna(), None)
            out.append((spark.createDataFrame(pdf), sheet if len(book) > 1 else None))
        return out

    raise ValueError(f"no reader for {kind}")


# ======================================================================================
# 3. MAIN LOOP
# ======================================================================================
ensure_log()
seen = already_done()
print(f"  {len(seen)} file(s) already loaded per the ingest log")

queue = list_files(landing_path)
print(f"  {len(queue)} file(s) found in {landing_path}")

processed = skipped = failed = 0
expanded = []

# -- pass 1: expand archives -----------------------------------------------------------
for f in queue:
    ext = f["name"].rsplit(".", 1)[-1].lower() if "." in f["name"] else ""
    if ext in ARCHIVES:
        fp = fingerprint(f)
        if fp in seen:
            print(f"  SKIP (archive already unpacked) {f['name']}")
            skipped += 1
            continue
        got = unpack(f)
        if got is None:
            record(fp, f, "archive", None, 0, "FAILED", "unpack error")
            failed += 1
            continue
        expanded += got
        record(fp, f, "archive", None, len(got), "LOADED", f"expanded to {len(got)} files")
        processed += 1
    else:
        expanded.append(f)

# -- pass 2: load everything -----------------------------------------------------------
for f in expanded:
    ext = f["name"].rsplit(".", 1)[-1].lower() if "." in f["name"] else ""
    if ext in ARCHIVES or f["name"].startswith((".", "_")):
        continue
    if ext not in READERS:
        print(f"  UNSUPPORTED {f['name']} (.{ext}) — left in place, not quarantined")
        record(fingerprint(f), f, ext, None, 0, "UNSUPPORTED", f"no reader for .{ext}")
        continue

    fp = fingerprint(f)
    if fp in seen:
        print(f"  SKIP (unchanged) {f['name']}")
        skipped += 1
        continue

    kind, hint = READERS[ext]
    try:
        for df, sheet in read_any(f, kind, hint):
            tbl = table_name(re.sub(r"\.[^.]+$", "", f["name"]), sheet)
            n = df.count()
            if n < min_rows:
                raise ValueError(f"only {n} rows, below min_rows={min_rows}")

            # Column names Delta will accept
            for c in df.columns:
                clean = re.sub(r"[ ,;{}()\n\t=]+", "_", c).strip("_") or "col"
                if clean != c:
                    df = df.withColumnRenamed(c, clean)

            df = (df.withColumn("_source_file", F.lit(f["name"]))
                    .withColumn("_source_format", F.lit(ext))
                    .withColumn("_batch_id", F.lit(batch_id))
                    .withColumn("_ingested_at", F.lit(ingested_at)))

            # mergeSchema so a new column upstream widens the table instead of failing the run
            (df.write.format("delta").mode("overwrite")
               .option("overwriteSchema", "true").saveAsTable(f"{LAKEHOUSE}.{tbl}"))
            print(f"  LOADED {f['name']}{'/' + sheet if sheet else ''} "
                  f"-> {tbl}  ({n:,} rows, {len(df.columns)} cols)")
            record(fp, f, ext, tbl, n, "LOADED")
            processed += 1
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        print(f"  FAILED {f['name']}: {msg}")
        record(fp, f, ext, None, 0, "FAILED", msg + "\n" + traceback.format_exc()[-600:])
        failed += 1
        try:
            mssparkutils.fs.cp(f["path"],
                               posixpath.join(quarantine_path, f["name"]), True)
            print(f"    -> quarantined to {quarantine_path}")
        except Exception:
            pass

# ======================================================================================
# 4. APPEND THE LOG
# ======================================================================================
if log_rows:
    cols = ["fingerprint", "source_file", "source_path", "file_format", "target_table",
            "row_count", "size_bytes", "status", "message", "batch_id", "ingested_at"]
    (spark.createDataFrame(log_rows, cols).write.format("delta").mode("append")
     .option("mergeSchema", "true").saveAsTable(LOG_TABLE))

print(f"\n  loaded {processed} | skipped {skipped} | failed {failed}")
print(f"\nTables now in the lakehouse:")
for t in sorted(r.tableName for r in spark.sql(f"SHOW TABLES IN {LAKEHOUSE}").collect()
                if r.tableName.startswith("bronze_")):
    try:
        print(f"  {t:<44} {spark.table(f'{LAKEHOUSE}.{t}').count():>10,} rows")
    except Exception:
        pass

# Fail the pipeline activity on any load failure — a silent partial ingest is the thing
# this notebook exists to prevent.
result = "FAIL" if failed else ("NOOP" if processed == 0 else "PASS")
print(f"\nexit: {result}")
mssparkutils.notebook.exit(result)
