import datetime as dt
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from media_audit import Auditor


def resolve(embedded, name="2020-01-01_photo.jpg", folder_year=1999):
    row = {"name":name,"embedded_creation_time":embedded,
           "birth_ts":dt.datetime(2020,1,1,12).timestamp(),
           "mtime_ts":dt.datetime(2020,1,1,12).timestamp(),
           "folder_year":folder_year,"relpath":f"Photos/{folder_year}/{name}"}
    object.__new__(Auditor).resolve_date(row)
    return row


# Embedded metadata wins even when names, folder years or filesystem dates disagree.
for embedded, expected in (("2023:06:15 10:30:00","2023-06-15"),
                           ("2020-01-02T00:01:00Z","2020-01-02"),
                           ("2026-10-26T11:00:00+01:00","2026-10-26")):
    row=resolve(embedded)
    assert row['best_date']==expected and row['date_source']=='embedded',row
    assert row['date_confidence']=='HIGH' and row['folder_year_mismatch']
for missing in (None,"","not-a-date","2023:02:30 10:00:00","2023"):
    row=resolve(missing,name="2020-01-01_photo.jpg",folder_year=2020)
    assert row['best_date'] is None and row['date_confidence']=='UNKNOWN',row
    assert row['date_source'] is None
print('Embedded dates override filename, folder and filesystem dates; no fallback when missing: PASS')
