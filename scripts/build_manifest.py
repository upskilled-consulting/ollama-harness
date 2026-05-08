"""Index email_drafts/*.json into email_drafts/manifest.json."""
import json
from pathlib import Path

ROOT   = Path(__file__).parent.parent
drafts = ROOT / "email_drafts"

files = [f.name for f in drafts.glob("*.json") if f.name != "manifest.json"]

with open(drafts / "manifest.json", "w") as f:
    json.dump(files, f, indent=2)

print(f"Indexed {len(files)} files")
