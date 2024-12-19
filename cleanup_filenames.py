from pathlib import Path
import shutil


def rename(file):
    for line in file.read_text().splitlines():
        if line.startswith("# "):
            title = line.split("# ", 1)[-1].strip()
    dest = file.with_stem("-".join(title.lower().split()))
    if file != dest:
        shutil.move(file, dest)
    return title, dest

nav, index = [], []
for file in Path("./docs").glob("*.md"):
    if file.name == "index.md":
        continue

    title, dest = rename(file)

    nav_entry = f"    - \"{dest.name}\""
    nav.append(nav_entry)

    index_entry = f"- [{title}]({dest.name})"
    index.append(index_entry)

print("\n".join(sorted(nav)))

with open("docs/index.md", "w") as f:
    f.write("# Family Recipes\n\n")
    f.write("\n".join(sorted(index)))
    f.write("\n")
