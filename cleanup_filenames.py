from pathlib import Path
import shutil


def rename(file):
    dest = file.with_stem("-".join(file.stem.lower().split()))
    if file != dest:
        shutil.move(file, dest)
    return dest

nav, index = [], []
for file in Path("./docs").glob("*.md"):
    if file.name == "index.md":
        continue

    dest = rename(file)
    title = " ".join(dest.stem.split("-")).title()

    nav_entry = f"    - {title}: \"{dest.name}\""
    nav.append(nav_entry)

    index_entry = f"- [{title}]({dest.name})"
    index.append(index_entry)

print("\n".join(nav))
print("\n".join(index))
