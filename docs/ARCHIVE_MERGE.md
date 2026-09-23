# Archive comparison and consolidated project

Compared:
- A: D:\project files\larp\hack-ee0863ec-larp.zip
- B: C:\Users\tofha\Downloads\hack-ee0863ec-larp.zip

All application, interface, configuration, example, and test text files are
identical after normalizing line endings. Neither archive adds code features
missing from the other. Environment folders and generated caches are not
source improvements and were not imported.

A is the more complete data snapshot: its SQLite database contains 166 profiles,
including 113 explicitly synthetic profiles. B contains 66 profiles, including
13 synthetic profiles. All 53 non-synthetic profiles are unchanged; the 13 shared
synthetic records in A have explicit (syn) names and completed fields.
A adds 100 unique synthetic IDs. B has no unique contractor IDs to preserve.

The workspace already matched A. The consolidated version retains the common
code and A's database, and exports the same 166 validated records into the CSV
seed so fresh installations receive the complete catalogue. The original
66-record CSV is retained under tests/fixtures for historical example tests.
No downloaded model, virtual environment, Git history, or generated response
cache was copied from either archive.