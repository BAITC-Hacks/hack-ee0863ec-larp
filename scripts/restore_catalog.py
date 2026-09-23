"""Restore a catalogue backup and back up the current state first."""
import argparse
import json
import tempfile
from pathlib import Path
from hackalem.catalog_store import DATABASE, read_profiles, import_catalog

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backup',type=Path)
    parser.add_argument('--database',type=Path,default=DATABASE)
    args=parser.parse_args()
    if not args.backup.is_file():
        parser.error('Backup does not exist.')
    rows=read_profiles(args.backup)
    with tempfile.TemporaryDirectory() as folder:
        source=Path(folder)/'restore.jsonl'
        source.write_text('\n'.join(json.dumps(p,ensure_ascii=False) for p in rows),encoding='utf-8')
        count=import_catalog(source,args.database)
    print(f'Restored {count} profiles; previous data saved under data/backups.')

if __name__=='__main__':
    main()