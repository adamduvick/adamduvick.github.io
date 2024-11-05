from pathlib import Path
import shutil

for file in Path("./").glob("*.md"):
    dest = file.with_stem("-".join(file.stem.lower().split()))
    if file != dest:
        shutil.move(file, dest)
