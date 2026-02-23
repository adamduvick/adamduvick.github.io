import logging
import os
import re
from pathlib import Path, PurePosixPath

log = logging.getLogger("mkdocs.hooks")

# ---------------------------------------------------------------------------
# Wiki-link resolution engine
# ---------------------------------------------------------------------------
#
# Page links (in any .md file):
#   [[page-name]]                -> auto-resolve, use page title as display text
#   [[page-name|Display Text]]   -> auto-resolve, custom display text
#   [[subfolder/page-name]]      -> partial-path disambiguated resolve
#   [[subfolder/page-name|Text]] -> partial-path disambiguated, custom text
#   [[page-name#heading]]        -> resolve page + append #heading anchor
#   [[page-name#heading|Text]]   -> resolve page + anchor, custom display text
#   [[#heading]]                 -> same-page anchor link
#   [[#heading|Text]]            -> same-page anchor link, custom display text
#
# Image / asset embeds:
#   ![[diagram.png]]                    -> image, alt text derived from filename
#   ![[diagram.png|Architecture overview]] -> image, custom alt text
#   ![[subfolder/diagram.png]]          -> partial-path disambiguated
#   ![[report.pdf]]                     -> non-image asset, rendered as download link
#   ![[diagram.png]]{: .center width="500"} -> image with attr_list attributes
#   ![[logo.png]](:target-page)         -> image as button linking to target-page
#   ![[logo.png|Alt]]{: .cls}(:page)    -> full combo: alt, attrs, link target
#
# All images are automatically wrapped in a click-to-enlarge link unless
# (:link-target) is specified, in which case the image links to that page.
# Attribute lists ({: ...}) are applied to the <img> tag, not the <a> wrapper.
# The (:...) link target is resolved using the same wiki-link engine as [[...]].
#
# Supported asset extensions:
#   Images: .png, .jpg, .jpeg, .gif, .webp, .svg
#   Other:  .pdf, .zip, .csv, .xlsx, .docx (rendered as download links)
#
# Resolution order (same for pages and assets):
#   1. Exact filename match (stem only, e.g. "setup" matches "setup.md")
#   2. If ambiguous, partial-path suffix match (e.g. "api/setup" matches
#      "docs/reference/api/setup.md")
#   3. If still ambiguous or no match, emit a build warning and leave the
#      link as-is (rendered as bold red text so authors notice it).
#
# The lookup index is built once in on_files() so we only walk the file
# list once per build.
# ---------------------------------------------------------------------------

# Regex for wiki-links: [[target]] or [[target|display text]]
# Avoids matching inside fenced code blocks (handled separately).
WIKI_LINK_RE = re.compile(
    r"\[\["
    r"(?P<target>[^\]|]+?)"  # target: everything up to | or ]]
    r"(?:\|(?P<display>[^\]]+))?"  # optional |display text
    r"\]\]"
)

# Regex for image/asset wiki-links: ![[target]] or ![[target|alt text]]
# Optionally captures:
#   - {: ...}  attribute list for the <img> tag
#   - (:target) link target (image becomes a button linking to target)
# Full syntax: ![[image.png|alt text]]{: .class width="x"}(:link-target)
WIKI_IMAGE_RE = re.compile(
    r"!\[\["
    r"(?P<target>[^\]|]+?)"  # target: everything up to | or ]]
    r"(?:\|(?P<alt>[^\]]+))?"  # optional |alt text
    r"\]\]"
    r"(?P<attrs>\{:[^}]+\})?"  # optional {: .class width="x" }
    r"(?:\(:(?P<link>[^)]+)\))?"  # optional (:link-target)
)

# File extensions recognised as embeddable images
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}

# All asset extensions we'll index (images + downloadable files)
ASSET_EXTENSIONS = IMAGE_EXTENSIONS | {
    ".pdf",
    ".zip",
    ".csv",
    ".xlsx",
    ".docx",
    ".yml",
    ".yaml",
    ".json",
    ".xml",
    ".toml",
    ".txt",
    ".cfg",
    ".ini",
    ".conf",
}

# Standard markdown links and images (not wiki-links)
_MD_LINK_RE = re.compile(r"(?P<img>!?)\[(?P<text>[^\]]*)\]\((?P<url>[^)]+)\)")


def _strip_code_fences(markdown):
    """
    Return list of (start, end) char ranges that are inside fenced code
    blocks or inline code, so we can skip wiki-links inside them.
    """
    ranges = []
    # Fenced blocks: opening ``` or ~~~ at start of line, closed by matching
    # fence at start of a subsequent line.
    for m in re.finditer(
        r"^(?P<fence>`{3,}|~{3,})[^\n]*\n.*?^(?P=fence)\s*$",
        markdown,
        re.MULTILINE | re.DOTALL,
    ):
        ranges.append((m.start(), m.end()))
    # Inline code: backtick pairs on the same line (no newline crossing).
    # Handles single and double backtick delimiters.
    for m in re.finditer(r"(?<!`)(`{1,2})(?!`)((?:(?!\1)[^\n])+)\1(?!`)", markdown):
        ranges.append((m.start(), m.end()))
    return ranges


def _inside_code(pos, code_ranges):
    return any(start <= pos < end for start, end in code_ranges)


def _make_relative_url(target_file, current_page):
    """
    Build a relative URL from current_page to target_file.

    Since wiki-links are resolved during on_page_markdown (i.e. we're
    outputting markdown, not HTML), the URLs must be relative in
    **source-tree** terms.  MkDocs' own markdown processing will then
    handle any dest_path / use_directory_urls translation.
    """
    from posixpath import relpath as posix_relpath

    current_src = PurePosixPath(current_page.file.src_path)
    target_src = PurePosixPath(target_file.src_path)

    current_dir = current_src.parent
    rel = posix_relpath(str(target_src), str(current_dir))
    return rel


def slugify(value):
    """Slugify a heading the same way markdown.extensions.toc does."""
    value = value.strip().lower()
    value = re.sub(r"[^\w\s-]", "", value)
    value = re.sub(r"[\s]+", "-", value)
    value = re.sub(r"[-]+", "-", value)
    return value


def extract_heading_slugs(markdown_text):
    """
    Extract heading slugs from markdown text using ATX heading syntax.
    Excludes headings inside fenced code blocks.
    """
    slugs = []
    in_fence = False
    fence_pattern = re.compile(r"^(`{3,}|~{3,})")

    for line in markdown_text.split("\n"):
        stripped = line.strip()
        fence_match = fence_pattern.match(stripped)
        if fence_match:
            if in_fence:
                in_fence = False
            else:
                in_fence = True
            continue
        if in_fence:
            continue
        heading_match = re.match(r"^#{1,6}\s+(.+?)(?:\s*#*\s*)?$", line)
        if heading_match:
            text = heading_match.group(1).strip()
            # Strip inline markup for slugification
            text = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", text)
            text = re.sub(r"_{1,2}(.+?)_{1,2}", r"\1", text)
            text = re.sub(r"`(.+?)`", r"\1", text)
            text = re.sub(r"\[(.+?)\]\([^)]*\)", r"\1", text)
            slugs.append(slugify(text))

    return slugs


class WikiLinkEngine:
    """Encapsulates all mutable state and logic for wiki-link resolution."""

    def __init__(self):
        # Page indexes
        self.page_index_by_stem = {}
        self.page_index_by_path = {}
        self.page_titles = {}

        # Asset indexes
        self.asset_index_by_name = {}
        self.asset_index_by_path = {}

        # Referenced asset tracking
        self.referenced_assets = set()

        # Legacy link report
        self.legacy_link_report = []

        # Quality flags
        self.quality_issues_found = False
        self.report_quality_issues = False

        # Auto-append config
        self.auto_append_files = []
        self.auto_append_base = None

        # Heading index for anchor validation
        self.heading_index = {}

    # ------------------------------------------------------------------
    # Index building
    # ------------------------------------------------------------------

    def build_indexes(self, files):
        """Build lookup structures from the MkDocs file list.

        Special handling for index.md pages:
          - They are registered under their **parent folder name** as the stem,
            so [[atlas]] resolves to atlas/index.md.
          - They are also registered by full path without the /index suffix,
            so [[systems/atlas]] works for partial-path disambiguation.
          - The bare stem "index" is never registered (it would be useless).

        Assets (images, PDFs, etc.) are indexed separately by full filename
        (with extension) so that ![[diagram.png]] works.
        """
        self.page_index_by_stem = {}
        self.page_index_by_path = {}
        self.asset_index_by_name = {}
        self.asset_index_by_path = {}
        self.referenced_assets.clear()
        self.legacy_link_report = []
        self.heading_index = {}

        for f in files:
            src = f.src_path
            p = PurePosixPath(src)
            ext = p.suffix.lower()

            if ext in ASSET_EXTENSIONS:
                filename = p.name.lower()
                self.asset_index_by_path[src.lower()] = f

                if filename not in self.asset_index_by_name:
                    self.asset_index_by_name[filename] = []
                self.asset_index_by_name[filename].append(f)
                continue

            if not src.endswith(".md"):
                continue

            stem = p.stem.lower()
            path_no_ext = src.rsplit(".", 1)[0].lower()

            self.page_index_by_path[path_no_ext] = f

            if stem == "index":
                parent = p.parent
                if parent != PurePosixPath("."):
                    folder_name = parent.name.lower()

                    if folder_name not in self.page_index_by_stem:
                        self.page_index_by_stem[folder_name] = []
                    self.page_index_by_stem[folder_name].append(f)

                    folder_path = str(parent).lower()
                    self.page_index_by_path[folder_path] = f
            else:
                if stem not in self.page_index_by_stem:
                    self.page_index_by_stem[stem] = []
                self.page_index_by_stem[stem].append(f)

    # ------------------------------------------------------------------
    # Unified disambiguation
    # ------------------------------------------------------------------

    @staticmethod
    def _page_effective_path(f):
        """Return the effective path for page disambiguation.

        For index.md pages, use the parent folder path.
        For other pages, use the path without extension.
        """
        p = PurePosixPath(f.src_path.lower())
        if p.stem == "index" and p.parent != PurePosixPath("."):
            return str(p.parent)
        return str(p.with_suffix(""))

    @staticmethod
    def _asset_effective_path(f):
        """Return the effective path for asset disambiguation (just the src_path)."""
        return f.src_path.lower()

    def _resolve_by_index(self, normalised, parts, index_by_key, index_by_path,
                          effective_path_fn, current_page_path, label_prefix=""):
        """Unified resolution: exact path -> key lookup -> partial-path -> proximity.

        Args:
            normalised: lowercased, normalised target string
            parts: normalised.split("/")
            index_by_key: dict mapping key (stem/filename) -> list of File objects
            index_by_path: dict mapping full path -> File object
            effective_path_fn: callable(File) -> str for disambiguation path
            current_page_path: src_path of the current page
            label_prefix: prefix for error messages (e.g. "!" for assets)

        Returns:
            (file_obj_or_None, warning_or_None)
        """
        key = parts[-1]
        raw = normalised  # for error messages

        # --- 1. Exact full-path match ---
        if normalised in index_by_path:
            return index_by_path[normalised], None

        # --- 2. Key-only lookup ---
        candidates = index_by_key.get(key, [])

        if not candidates:
            return None, f"{label_prefix}Wiki-link target not found: {label_prefix}[[{raw}]]" if not label_prefix else f"Asset not found: ![[{raw}]]"

        if len(candidates) == 1 and len(parts) == 1:
            return candidates[0], None

        # --- 3. Partial-path matching for disambiguation ---
        if len(parts) > 1:
            hint_segments = parts[:-1]

            def _matches_hint(f):
                path_parts = effective_path_fn(f).split("/")
                search_from = 0
                for seg in hint_segments:
                    try:
                        idx = path_parts.index(seg, search_from)
                        search_from = idx + 1
                    except ValueError:
                        return False
                return True

            matches = [f for f in candidates if _matches_hint(f)]
            if len(matches) == 1:
                return matches[0], None
            if len(matches) > 1:
                paths = [m.src_path for m in matches]
                if label_prefix:
                    return None, (
                        f"Ambiguous asset ![[{raw}]] — still matches "
                        f"{len(matches)} files: {', '.join(paths)}.  Add more path segments "
                        f"to disambiguate."
                    )
                return None, (
                    f"\nAmbiguous wiki-link [[{raw}]] — still matches {len(matches)} pages:"
                    f"\n\t{chr(10).join(chr(9) + p for p in paths[1:])}"
                    f"{chr(10)}\t{paths[0]}"
                    f"\nAdd more path segments to disambiguate."
                )

        # --- 4. Proximity tie-breaking ---
        if len(candidates) > 1 and len(parts) == 1:
            current_dir_parts = current_page_path.lower().split("/")[:-1]

            def _shared_prefix_len(f):
                f_parts = f.src_path.lower().split("/")[:-1]
                common = 0
                for a, b in zip(current_dir_parts, f_parts):
                    if a == b:
                        common += 1
                    else:
                        break
                return common

            scored = sorted(candidates, key=_shared_prefix_len, reverse=True)
            best_score = _shared_prefix_len(scored[0])
            top_tier = [f for f in scored if _shared_prefix_len(f) == best_score]

            if len(top_tier) == 1:
                return top_tier[0], None

            paths = [c.src_path for c in candidates]
            if label_prefix:
                return None, (
                    f"Ambiguous asset ![[{raw}]] — matches {len(candidates)} "
                    f"files: {', '.join(paths)}.  Use a partial path like "
                    f"![[folder/{raw}]] to disambiguate."
                )
            return None, (
                f"\nAmbiguous wiki-link [[{raw}]] — matches {len(candidates)} pages: "
                f"\n\t{chr(10).join(chr(9) + p for p in paths[1:])}"
                f"{chr(10)}\t{paths[0]}"
                f"\nUse a partial path like [[folder/{raw}]] to disambiguate."
            )

        # Fallback
        paths = [c.src_path for c in candidates]
        if label_prefix:
            return None, f"Could not resolve asset ![[{raw}]] — candidates: {', '.join(paths)}"
        return None, (
            f"Could not resolve wiki-link [[{raw}]] — candidates: "
            f"\n\t{chr(10).join(chr(9) + p for p in paths[1:])}"
            f"{chr(10)}\t{paths[0]}"
        )

    def _shortest_disambiguation(self, target_file, candidates, parts_fn):
        """Find the shortest partial path that uniquely identifies target among candidates.

        Args:
            target_file: the target File object
            candidates: list of candidate File objects
            parts_fn: callable(File) -> list of path parts for matching
        """
        target_parts = parts_fn(target_file)
        target_parts_lower = [p.lower() for p in target_parts]

        for length in range(2, len(target_parts_lower) + 1):
            check_segments = target_parts_lower[-length:]

            def _matches(f):
                f_parts = [p.lower() for p in parts_fn(f)]
                search_from = 0
                for seg in check_segments:
                    try:
                        idx = f_parts.index(seg, search_from)
                        search_from = idx + 1
                    except ValueError:
                        return False
                return True

            matches = [f for f in candidates if _matches(f)]
            if len(matches) == 1:
                return "/".join(target_parts[-length:])

        return "/".join(target_parts)

    @staticmethod
    def _page_parts(f):
        """Path parts for page disambiguation."""
        p = PurePosixPath(f.src_path)
        if p.stem == "index" and p.parent != PurePosixPath("."):
            return list(p.parent.parts)
        return list(p.with_suffix("").parts)

    @staticmethod
    def _asset_parts(f):
        """Path parts for asset disambiguation."""
        return list(PurePosixPath(f.src_path).parts)

    # ------------------------------------------------------------------
    # Page resolution
    # ------------------------------------------------------------------

    def resolve_wiki_link(self, target, current_page_path):
        """
        Resolve a wiki-link target string to a File object (or None).
        Handles anchor fragments: [[page-name#section]] resolves page-name
        and preserves the #section for the final URL.

        Returns (file_obj, anchor_or_empty_str, warning_message_or_None).
        """
        raw = target.strip()

        # --- Strip anchor fragment before resolution ---
        anchor = ""
        if "#" in raw:
            raw_path, anchor = raw.split("#", 1)
            anchor = f"#{anchor}"
            raw_path = raw_path.strip()
        else:
            raw_path = raw

        # Handle bare anchor (e.g. [[#section]]) — link to current page heading
        if not raw_path:
            return None, anchor, None

        # Normalise: lowercase, forward slashes, strip .md if someone added it
        normalised = raw_path.lower().replace("\\", "/")
        if normalised.endswith(".md"):
            normalised = normalised[:-3]

        # --- If target has an asset extension, delegate to asset resolver ---
        target_ext = PurePosixPath(normalised).suffix.lower()
        if target_ext in ASSET_EXTENSIONS and target_ext not in (".md",):
            resolved, warning = self.resolve_asset_link(raw_path, current_page_path)
            if warning:
                return None, anchor, warning
            return resolved, anchor, None

        parts = normalised.split("/")

        resolved, warning = self._resolve_by_index(
            normalised, parts,
            self.page_index_by_stem, self.page_index_by_path,
            self._page_effective_path, current_page_path,
        )

        if warning:
            return None, anchor, warning
        return resolved, anchor, None

    # ------------------------------------------------------------------
    # Asset resolution
    # ------------------------------------------------------------------

    def resolve_asset_link(self, target, current_page_path):
        """
        Resolve an asset wiki-link target (![[...]]) to a File object.
        Returns (file_obj, warning_message_or_None).
        """
        raw = target.strip()
        normalised = raw.lower().replace("\\", "/")
        parts = normalised.split("/")

        return self._resolve_by_index(
            normalised, parts,
            self.asset_index_by_name, self.asset_index_by_path,
            self._asset_effective_path, current_page_path,
            label_prefix="!",
        )

    # ------------------------------------------------------------------
    # Anchor validation
    # ------------------------------------------------------------------

    def _get_heading_slugs(self, src_path, docs_dir=None):
        """Get heading slugs for a page, with lazy caching.

        For the current page, headings are cached from the in-memory markdown
        via cache_current_page_headings(). For other pages, reads from disk.
        """
        if src_path in self.heading_index:
            return self.heading_index[src_path]

        # Read from disk
        if docs_dir:
            full_path = Path(docs_dir) / src_path
            if full_path.is_file():
                try:
                    text = full_path.read_text(encoding="utf-8")
                    slugs = extract_heading_slugs(text)
                    self.heading_index[src_path] = slugs
                    return slugs
                except Exception:
                    pass

        return []

    def cache_current_page_headings(self, src_path, markdown_text):
        """Cache heading slugs for the current page from in-memory markdown."""
        self.heading_index[src_path] = extract_heading_slugs(markdown_text)

    def validate_anchor(self, anchor, target_src_path, docs_dir=None):
        """Validate that an anchor exists on the target page.

        Args:
            anchor: the anchor string including '#', e.g. '#my-heading'
            target_src_path: src_path of the target page
            docs_dir: path to docs directory for disk reads

        Returns:
            (is_valid, available_headings) — True if valid or can't check,
            plus list of available heading slugs.
        """
        if not anchor or not anchor.startswith("#"):
            return True, []

        slug = anchor[1:]  # strip leading #
        if not slug:
            return True, []

        slugs = self._get_heading_slugs(target_src_path, docs_dir)
        if not slugs:
            # Can't validate — no headings found (or file not readable)
            return True, []

        return slug in slugs, slugs

    # ------------------------------------------------------------------
    # Display text helpers
    # ------------------------------------------------------------------

    def _get_display_text(self, target_raw, target_file):
        """
        Determine display text for a resolved link.
        Prefer the page's H1 title if we've seen it; otherwise humanise the
        filename stem (or parent folder name for index.md pages).
        """
        src = target_file.src_path
        if src in self.page_titles:
            return self.page_titles[src]
        p = PurePosixPath(src)
        if p.stem == "index" and p.parent != PurePosixPath("."):
            name = p.parent.name
        else:
            name = p.stem
        return name.replace("-", " ").replace("_", " ").title()

    @staticmethod
    def _get_asset_alt_text(target_raw, target_file):
        """
        Derive alt text from the asset filename.
        "my-architecture-diagram.png" -> "My Architecture Diagram"
        """
        stem = PurePosixPath(target_file.src_path).stem
        return stem.replace("-", " ").replace("_", " ").title()

    # ------------------------------------------------------------------
    # Main markdown replacement entry point
    # ------------------------------------------------------------------

    def resolve_all_wiki_links(self, markdown, page, config, files):
        """
        Find and replace all [[wiki-links]] and ![[asset-links]] in the given
        markdown.  Returns the transformed markdown.
        """
        code_ranges = _strip_code_fences(markdown)
        warnings = []
        docs_dir = config.get("docs_dir", ".")

        # --- Process ![[asset]] links first (so the ! isn't left behind) ---
        def _replace_asset(match):
            if _inside_code(match.start(), code_ranges):
                return match.group(0)

            target_raw = match.group("target")
            alt = match.group("alt")
            attrs = match.group("attrs") or ""
            link_target = match.group("link")

            resolved, warning = self.resolve_asset_link(target_raw, page.file.src_path)

            if warning:
                warnings.append(warning)
                label = alt or target_raw
                return (
                    f'<span style="color:red;font-weight:bold" '
                    f'title="{warning}">⚠ {label}</span>'
                )

            url = _make_relative_url(resolved, page)
            alt_text = alt or self._get_asset_alt_text(target_raw, resolved)
            ext = PurePosixPath(resolved.src_path).suffix.lower()

            # Track this asset as referenced
            self.referenced_assets.add(resolved.src_path)

            if ext in IMAGE_EXTENSIONS:
                img = f"![{alt_text}]({url}){attrs}"

                if link_target:
                    # Check if it's an external URL — pass through directly
                    if link_target.startswith(("http://", "https://", "//", "mailto:")):
                        return f"[{img}]({link_target})"

                    # Image-as-button: resolve the link target as a page wiki-link
                    link_resolved, link_anchor, link_warning = self.resolve_wiki_link(
                        link_target, page.file.src_path
                    )
                    if link_warning:
                        warnings.append(link_warning)
                        return (
                            f'<span style="color:red;font-weight:bold" '
                            f'title="{link_warning}">⚠ {alt_text}</span>'
                        )
                    if link_resolved is None and link_anchor:
                        # Bare anchor
                        return f"[{img}]({link_anchor})"
                    link_url = _make_relative_url(link_resolved, page) + link_anchor
                    return f"[{img}]({link_url})"
                else:
                    # Default: click-to-enlarge (link to image itself)
                    return f"[{img}]({url})"
            else:
                # Non-image asset: render as a download link
                return f"[{alt_text}]({url}){attrs}"

        markdown = WIKI_IMAGE_RE.sub(_replace_asset, markdown)

        # --- Then process [[page]] links ---
        # (Re-compute code ranges since asset replacement may have shifted positions)
        code_ranges = _strip_code_fences(markdown)

        def _replace_page(match):
            if _inside_code(match.start(), code_ranges):
                return match.group(0)

            target_raw = match.group("target")
            display = match.group("display")

            resolved, anchor, warning = self.resolve_wiki_link(target_raw, page.file.src_path)

            if warning:
                warnings.append(warning)
                label = display or target_raw
                return (
                    f'<span style="color:red;font-weight:bold" '
                    f'title="{warning}">⚠ {label}</span>'
                )

            # Bare anchor only (e.g. [[#section]]) — link to heading on same page
            if resolved is None and anchor:
                # Validate anchor on current page
                is_valid, available = self.validate_anchor(
                    anchor, page.file.src_path, docs_dir
                )
                if not is_valid:
                    label = display or anchor[1:]
                    hint = ", ".join(available[:10])
                    tip = f"Anchor {anchor} not found. Available: {hint}"
                    warnings.append(f"{page.file.src_path}: {tip}")
                    return (
                        f'<span style="color:red;font-weight:bold" '
                        f'title="{tip}">⚠ {label}</span>'
                    )
                label = display or anchor[1:]
                return f"[{label}]({anchor})"

            url = _make_relative_url(resolved, page) + anchor
            label = display or self._get_display_text(target_raw, resolved)

            # Validate anchor on target page
            if anchor:
                is_valid, available = self.validate_anchor(
                    anchor, resolved.src_path, docs_dir
                )
                if not is_valid:
                    hint = ", ".join(available[:10])
                    tip = f"Anchor {anchor} not found on {resolved.src_path}. Available: {hint}"
                    warnings.append(tip)
                    return (
                        f'<span style="color:red;font-weight:bold" '
                        f'title="{tip}">⚠ {label}</span>'
                    )

            # Track if this resolved to an asset (e.g. [[config.yml]])
            ext = PurePosixPath(resolved.src_path).suffix.lower()
            if ext in ASSET_EXTENSIONS:
                self.referenced_assets.add(resolved.src_path)

            return f"[{label}]({url})"

        result = WIKI_LINK_RE.sub(_replace_page, markdown)

        for w in warnings:
            log.warning(f"[wiki-link] {page.file.src_path}: {w}")

        return result

    # ------------------------------------------------------------------
    # Quality checks
    # ------------------------------------------------------------------

    def run_quality_checks(self, markdown, page):
        """Run quality checks on page markdown. Returns list of warnings."""
        path = page.file.src_path
        warnings = []

        title_match = re.search(r"^#\s+(.+)$", markdown, re.MULTILINE)
        if title_match:
            self.page_titles[path] = title_match.group(1).strip()

        if not title_match:
            warnings.append("Missing top-level heading")

        word_count = len(markdown.split())
        if word_count < 30:
            warnings.append(f"Stub page? Only {word_count} words")

        todos = re.findall(r"\b(TODO|FIXME|HACK|XXX)\b", markdown)
        if todos:
            warnings.append(f"Contains markers: {', '.join(set(todos))}")

        if re.search(r"^!!!\s*$", markdown, re.MULTILINE):
            warnings.append("Empty admonition block")

        if re.search(r"!\[\]\(", markdown):
            warnings.append("Image(s) missing alt text")

        if warnings:
            self.quality_issues_found = True

        if self.report_quality_issues:
            for w in warnings:
                log.warning(f"[quality] {path}: {w}")

        if os.getenv("CI") and os.getenv("DOCS_STRICT") and warnings:
            raise SystemExit(f"Quality check failed for {path}")

        return warnings

    # ------------------------------------------------------------------
    # Legacy link detection
    # ------------------------------------------------------------------

    def check_legacy_links(self, markdown, page):
        """
        Scan for standard markdown links/images pointing to internal pages or
        assets.  For each one found, suggest the wiki-link equivalent.
        """
        code_ranges = _strip_code_fences(markdown)
        src = page.file.src_path

        for match in _MD_LINK_RE.finditer(markdown):
            if _inside_code(match.start(), code_ranges):
                continue

            is_img = bool(match.group("img"))
            text = match.group("text")
            url = match.group("url").strip()

            if url.startswith(("http://", "https://", "//", "mailto:", "#")):
                continue

            if not is_img and "![" in text and "](" in text:
                continue

            anchor = ""
            if "#" in url:
                url_path, anchor_part = url.split("#", 1)
                anchor = f"#{anchor_part}"
            else:
                url_path = url

            if not url_path:
                continue

            target_file = self._find_target_file(url_path, page)
            if target_file is None:
                continue

            ext = PurePosixPath(target_file.src_path).suffix.lower()
            if ext in ASSET_EXTENSIONS:
                self.referenced_assets.add(target_file.src_path)

            suggestion = self._suggest_wikilink(target_file, text, anchor, is_img)
            if suggestion:
                original = match.group(0)
                self.legacy_link_report.append(f"{src}: {original}\n          -> {suggestion}")

    def _find_target_file(self, url_path, page):
        """
        Resolve a relative URL to a File object in the MkDocs files index.
        """
        from posixpath import join as posix_join
        from posixpath import normpath

        current_dir = str(PurePosixPath(page.file.src_path).parent)

        if url_path.startswith("/"):
            resolved = url_path.lstrip("/")
        else:
            resolved = normpath(posix_join(current_dir, url_path))

        resolved = resolved.rstrip("/")
        resolved_lower = resolved.lower()

        if resolved_lower in self.page_index_by_path:
            return self.page_index_by_path[resolved_lower]

        without_ext = resolved_lower
        if without_ext.endswith(".md"):
            without_ext = without_ext[:-3]
        if without_ext in self.page_index_by_path:
            return self.page_index_by_path[without_ext]

        if without_ext.endswith("/index"):
            folder = without_ext[:-6]
            if folder in self.page_index_by_path:
                return self.page_index_by_path[folder]

        as_index = resolved_lower + "/index"
        if as_index in self.page_index_by_path:
            return self.page_index_by_path[as_index]

        if resolved_lower in self.asset_index_by_path:
            return self.asset_index_by_path[resolved_lower]

        return None

    def _suggest_wikilink(self, target_file, display_text, anchor, is_image):
        """
        Given a resolved File object, produce the recommended wiki-link syntax.
        """
        src = target_file.src_path
        p = PurePosixPath(src)
        ext = p.suffix.lower()

        if ext == ".md":
            stem = p.stem.lower()
            if stem == "index":
                parent = p.parent
                if parent != PurePosixPath("."):
                    name = parent.name
                else:
                    return None
            else:
                name = p.stem

            stem_key = name.lower()
            candidates = self.page_index_by_stem.get(stem_key, [])

            if len(candidates) == 1:
                target = name
            else:
                target = self._shortest_disambiguation(
                    target_file, candidates, self._page_parts
                )

            target_with_anchor = f"{target}{anchor}" if anchor else target

            auto_display = name.replace("-", " ").replace("_", " ").title()
            if display_text and display_text.strip().lower() != auto_display.lower():
                return f"[[{target_with_anchor}|{display_text}]]"
            return f"[[{target_with_anchor}]]"

        elif ext in ASSET_EXTENSIONS:
            filename = p.name
            name_lower = filename.lower()
            candidates = self.asset_index_by_name.get(name_lower, [])

            if len(candidates) == 1:
                target = filename
            else:
                target = self._shortest_disambiguation(
                    target_file, candidates, self._asset_parts
                )

            auto_alt = p.stem.replace("-", " ").replace("_", " ").title()

            if ext in IMAGE_EXTENSIONS:
                if display_text and display_text.strip().lower() != auto_alt.lower():
                    return f"![[{target}|{display_text}]]"
                return f"![[{target}]]"
            else:
                if display_text and display_text.strip().lower() != auto_alt.lower():
                    return f"[[{target}|{display_text}]]"
                return f"[[{target}]]"

        return None

    # ------------------------------------------------------------------
    # Auto-append expansion
    # ------------------------------------------------------------------

    def expand_auto_append(self, markdown):
        """
        Append the content of auto_append files to the markdown.
        Resolves file paths using the same base_path logic as pymdownx.snippets.
        """
        for include_path in self.auto_append_files:
            content = None
            for base in self.auto_append_base:
                full = Path(base) / include_path
                if full.is_file():
                    content = full.read_text(encoding="utf-8")
                    break

            if content is None:
                log.warning(f"[wiki-link] auto_append file not found: {include_path}")
                continue

            if not markdown.endswith("\n\n"):
                markdown = markdown.rstrip("\n") + "\n\n"
            markdown += content

        return markdown

    # ------------------------------------------------------------------
    # Orphan asset detection
    # ------------------------------------------------------------------

    def check_orphan_assets(self, config):
        """
        Compare indexed assets against those referenced during the build.
        Report any assets that exist in the docs tree but are never linked to.
        """
        all_assets = set()
        for src_lower, f in self.asset_index_by_path.items():
            all_assets.add(f.src_path)

        orphans = sorted(all_assets - self.referenced_assets)

        def _ignore_orphan(path):
            return any(
                [
                    path.startswith("assets/"),
                    path.endswith(".meta.yml"),
                    path == "versions.json",
                ]
            )

        orphans = [o for o in orphans if not _ignore_orphan(o)]

        if not orphans:
            return

        log.warning("") 
        log.warning(f"[orphan] Found {len(orphans)} unreferenced asset(s):")
        for path in orphans:
            log.warning(f"  {path}")
        log.warning("")
        log.warning(
            "[orphan] These files are not linked from any page. "
            "Consider removing them or adding references."
        )


# ---------------------------------------------------------------------------
# Module-level singleton — re-created each build via on_config()
# ---------------------------------------------------------------------------

_engine = WikiLinkEngine()


# ---------------------------------------------------------------------------
# MkDocs hook entry points
# ---------------------------------------------------------------------------


def on_config(config, **kwargs):
    """Suppress noisy loggers, capture snippets auto_append, keep our own."""
    global _engine
    _engine = WikiLinkEngine()

    logging.getLogger("mkdocs.hooks").setLevel(logging.INFO)

    # --- Take over auto_append from pymdownx.snippets ---
    mdx_configs = config.get("mdx_configs", {})
    snippets_cfg = mdx_configs.get("pymdownx.snippets", {})

    if snippets_cfg.get("auto_append"):
        _engine.auto_append_files = list(snippets_cfg["auto_append"])

        base_path = snippets_cfg.get("base_path", ["."])
        if isinstance(base_path, str):
            base_path = [base_path]
        _engine.auto_append_base = [os.path.abspath(b) for b in base_path]

        snippets_cfg["auto_append"] = []
        log.info(
            f"[wiki-link] Took over {len(_engine.auto_append_files)} "
            f"auto_append file(s) from pymdownx.snippets"
        )

    return config


def on_files(files, config, **kwargs):
    """Build the wiki-link page index once per build."""
    _engine.build_indexes(files)
    log.info(
        f"[wiki-link] Indexed {len(_engine.page_index_by_path)} pages "
        f"({len(_engine.page_index_by_stem)} unique stems), "
        f"{len(_engine.asset_index_by_path)} assets "
        f"({len(_engine.asset_index_by_name)} unique names)"
    )
    return files


def on_page_markdown(markdown, page, config, files, **kwargs):
    """Quality checks + wiki-link resolution on each page's markdown."""
    # --- Quality checks ---
    _engine.run_quality_checks(markdown, page)

    # --- Append auto_append files (taken over from pymdownx.snippets) ---
    if _engine.auto_append_files:
        markdown = _engine.expand_auto_append(markdown)

    # --- Cache current page headings (after auto-append so appended headings are included) ---
    _engine.cache_current_page_headings(page.file.src_path, markdown)

    # --- Detect legacy markdown links (before wiki-link resolution) ---
    _engine.check_legacy_links(markdown, page)

    # --- Wiki-link resolution ---
    markdown = _engine.resolve_all_wiki_links(markdown, page, config, files)

    return markdown


def on_post_page(output_content, **kwargs):
    return output_content.replace("..\\scripts\\", "../scripts/")


def on_post_build(config, **kwargs):
    """Post-build summary."""
    if _engine.report_quality_issues and _engine.quality_issues_found:
        log.info("[quality] Build complete — review warnings above")
    if _engine.legacy_link_report:
        log.warning("")
        log.warning(
            f"[wiki-link] Found {len(_engine.legacy_link_report)} legacy markdown "
            f"link(s) that could be converted to wiki-links:"
        )
        for entry in _engine.legacy_link_report:
            log.warning(f"  {entry}")
        log.warning("")
        log.warning("[wiki-link] Run the migration script or convert manually.")

    _engine.check_orphan_assets(config)

    return config
