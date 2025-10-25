
#!/usr/bin/env python3
import os, zipfile
from datetime import datetime
from pathlib import Path

DATA_DIR = os.environ.get("BURTEQ_DATA_DIR", "data")
backup_dir = Path(DATA_DIR)/"backups"
backup_dir.mkdir(parents=True, exist_ok=True)

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
zip_path = backup_dir / f"burtequin_data_{ts}.zip"

with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk(DATA_DIR):
        for f in files:
            if f.endswith('.zip'):
                continue
            p = Path(root)/f
            zf.write(p, arcname=str(p.relative_to(DATA_DIR)))

print("Backup criado:", zip_path)
