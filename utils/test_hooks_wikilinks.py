"""Tests for hooks_wikilinks.py — no MkDocs runtime required."""

import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import pytest

from hooks_wikilinks import (
    ASSET_EXTENSIONS,
    IMAGE_EXTENSIONS,
    WikiLinkEngine,
    _inside_code,
    _strip_code_fences,
    extract_heading_slugs,
    slugify,
)


# ---------------------------------------------------------------------------
# Fake MkDocs objects — lightweight stand-ins for mkdocs.structure.files.File
# and mkdocs.structure.pages.Page so we can test without the MkDocs runtime.
# ---------------------------------------------------------------------------


@dataclass
class FakeFile:
    """Minimal stand-in for mkdocs.structure.files.File."""

    src_path: str
    dest_path: str = ""
    name: str = ""
    url: str = ""

    def __post_init__(self):
        if not self.name:
            self.name = PurePosixPath(self.src_path).name


@dataclass
class FakePage:
    """Minimal stand-in for mkdocs.structure.pages.Page."""

    file: FakeFile
    title: str = ""
    meta: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_engine(page_paths=None, asset_paths=None):
    """Create a WikiLinkEngine and build indexes from simple path lists."""
    engine = WikiLinkEngine()
    files = []
    for p in page_paths or []:
        files.append(FakeFile(src_path=p))
    for p in asset_paths or []:
        files.append(FakeFile(src_path=p))
    engine.build_indexes(files)
    return engine


def make_page(src_path):
    return FakePage(file=FakeFile(src_path=src_path))


# ===========================================================================
# 1. Page index building
# ===========================================================================


class TestPageIndexBuilding:
    def test_stem_indexing(self):
        engine = make_engine(page_paths=["docs/setup.md"])
        assert "setup" in engine.page_index_by_stem
        assert len(engine.page_index_by_stem["setup"]) == 1

    def test_index_md_uses_folder_name(self):
        engine = make_engine(page_paths=["docs/atlas/index.md"])
        assert "atlas" in engine.page_index_by_stem
        assert "index" not in engine.page_index_by_stem

    def test_index_md_folder_path_registered(self):
        engine = make_engine(page_paths=["docs/atlas/index.md"])
        assert "docs/atlas" in engine.page_index_by_path
        assert "docs/atlas/index" in engine.page_index_by_path

    def test_path_indexing(self):
        engine = make_engine(page_paths=["reference/api/setup.md"])
        assert "reference/api/setup" in engine.page_index_by_path

    def test_asset_indexing(self):
        engine = make_engine(asset_paths=["images/diagram.png"])
        assert "diagram.png" in engine.asset_index_by_name
        assert "images/diagram.png" in engine.asset_index_by_path

    def test_multiple_stems(self):
        engine = make_engine(
            page_paths=["docs/a/setup.md", "docs/b/setup.md"]
        )
        assert len(engine.page_index_by_stem["setup"]) == 2

    def test_root_index_not_indexed_by_stem(self):
        engine = make_engine(page_paths=["index.md"])
        assert "index" not in engine.page_index_by_stem

    def test_build_indexes_clears_previous(self):
        engine = make_engine(page_paths=["docs/old.md"])
        assert "old" in engine.page_index_by_stem
        engine.build_indexes([FakeFile(src_path="docs/new.md")])
        assert "old" not in engine.page_index_by_stem
        assert "new" in engine.page_index_by_stem


# ===========================================================================
# 2. Page resolution
# ===========================================================================


class TestPageResolution:
    def test_unique_stem(self):
        engine = make_engine(page_paths=["docs/setup.md"])
        resolved, anchor, warning = engine.resolve_wiki_link("setup", "docs/other.md")
        assert resolved.src_path == "docs/setup.md"
        assert anchor == ""
        assert warning is None

    def test_full_path(self):
        engine = make_engine(
            page_paths=["docs/a/setup.md", "docs/b/setup.md"]
        )
        resolved, anchor, warning = engine.resolve_wiki_link(
            "docs/a/setup", "docs/other.md"
        )
        assert resolved.src_path == "docs/a/setup.md"
        assert warning is None

    def test_case_insensitive(self):
        engine = make_engine(page_paths=["docs/Setup.md"])
        resolved, _, warning = engine.resolve_wiki_link("setup", "docs/other.md")
        assert resolved is not None
        assert warning is None

    def test_not_found(self):
        engine = make_engine(page_paths=["docs/setup.md"])
        resolved, _, warning = engine.resolve_wiki_link("nonexistent", "docs/other.md")
        assert resolved is None
        assert warning is not None
        assert "not found" in warning.lower()

    def test_anchor_preserved(self):
        engine = make_engine(page_paths=["docs/setup.md"])
        resolved, anchor, warning = engine.resolve_wiki_link(
            "setup#install", "docs/other.md"
        )
        assert resolved.src_path == "docs/setup.md"
        assert anchor == "#install"
        assert warning is None

    def test_bare_anchor(self):
        engine = make_engine(page_paths=["docs/setup.md"])
        resolved, anchor, warning = engine.resolve_wiki_link("#section", "docs/setup.md")
        assert resolved is None
        assert anchor == "#section"
        assert warning is None

    def test_md_extension_stripped(self):
        engine = make_engine(page_paths=["docs/setup.md"])
        resolved, _, warning = engine.resolve_wiki_link("setup.md", "docs/other.md")
        assert resolved.src_path == "docs/setup.md"
        assert warning is None

    def test_index_page_resolved_by_folder_name(self):
        engine = make_engine(page_paths=["docs/atlas/index.md"])
        resolved, _, warning = engine.resolve_wiki_link("atlas", "docs/other.md")
        assert resolved.src_path == "docs/atlas/index.md"
        assert warning is None

    def test_asset_extension_delegates(self):
        """Wiki-link with asset extension delegates to asset resolver."""
        engine = make_engine(asset_paths=["docs/config.yml"])
        resolved, _, warning = engine.resolve_wiki_link("config.yml", "docs/page.md")
        assert resolved.src_path == "docs/config.yml"
        assert warning is None


# ===========================================================================
# 3. Disambiguation
# ===========================================================================


class TestDisambiguation:
    def test_partial_path(self):
        engine = make_engine(
            page_paths=["docs/a/setup.md", "docs/b/setup.md"]
        )
        resolved, _, warning = engine.resolve_wiki_link(
            "a/setup", "docs/other.md"
        )
        assert resolved.src_path == "docs/a/setup.md"
        assert warning is None

    def test_ordered_segments(self):
        engine = make_engine(
            page_paths=[
                "general/cert-engine/software-cert-engine/triage/doc_ops.md",
                "general/cert-engine/systems-cert-engine/triage/doc_ops.md",
            ]
        )
        resolved, _, warning = engine.resolve_wiki_link(
            "software-cert-engine/doc_ops", "general/other.md"
        )
        assert resolved.src_path == "general/cert-engine/software-cert-engine/triage/doc_ops.md"
        assert warning is None

    def test_proximity_tiebreak(self):
        engine = make_engine(
            page_paths=["docs/a/notes.md", "docs/b/notes.md"]
        )
        resolved, _, warning = engine.resolve_wiki_link("notes", "docs/a/page.md")
        assert resolved.src_path == "docs/a/notes.md"
        assert warning is None

    def test_ambiguous_warning(self):
        engine = make_engine(
            page_paths=[
                "docs/a/sub/setup.md",
                "docs/b/sub/setup.md",
            ]
        )
        # Both share "sub/" prefix so partial path "sub/setup" still ambiguous
        resolved, _, warning = engine.resolve_wiki_link(
            "sub/setup", "other.md"
        )
        # Both match the hint, so it should be ambiguous
        assert warning is not None
        assert "ambiguous" in warning.lower() or resolved is not None


# ===========================================================================
# 4. Asset resolution
# ===========================================================================


class TestAssetResolution:
    def test_filename(self):
        engine = make_engine(asset_paths=["images/diagram.png"])
        resolved, warning = engine.resolve_asset_link("diagram.png", "docs/page.md")
        assert resolved.src_path == "images/diagram.png"
        assert warning is None

    def test_full_path(self):
        engine = make_engine(
            asset_paths=["images/a/diagram.png", "images/b/diagram.png"]
        )
        resolved, warning = engine.resolve_asset_link(
            "images/a/diagram.png", "docs/page.md"
        )
        assert resolved.src_path == "images/a/diagram.png"
        assert warning is None

    def test_proximity(self):
        engine = make_engine(
            asset_paths=["docs/a/photo.png", "docs/b/photo.png"]
        )
        resolved, warning = engine.resolve_asset_link("photo.png", "docs/a/page.md")
        assert resolved.src_path == "docs/a/photo.png"
        assert warning is None

    def test_not_found(self):
        engine = make_engine(asset_paths=["images/diagram.png"])
        resolved, warning = engine.resolve_asset_link("missing.png", "docs/page.md")
        assert resolved is None
        assert warning is not None

    def test_partial_path_disambiguation(self):
        engine = make_engine(
            asset_paths=["images/a/icon.svg", "images/b/icon.svg"]
        )
        resolved, warning = engine.resolve_asset_link("a/icon.svg", "docs/page.md")
        assert resolved.src_path == "images/a/icon.svg"
        assert warning is None


# ===========================================================================
# 5. Anchor validation
# ===========================================================================


class TestAnchorValidation:
    def test_extract_headings(self):
        md = "# Hello World\n## Sub Section\n### Deep Dive"
        slugs = extract_heading_slugs(md)
        assert slugs == ["hello-world", "sub-section", "deep-dive"]

    def test_slugify_basic(self):
        assert slugify("Hello World") == "hello-world"
        assert slugify("API Reference (v2)") == "api-reference-v2"

    def test_slugify_special_chars(self):
        assert slugify("What's New?") == "whats-new"
        assert slugify("C++ Guide") == "c-guide"

    def test_code_fences_excluded(self):
        md = "# Real Heading\n```\n# Not A Heading\n```\n## Another"
        slugs = extract_heading_slugs(md)
        assert "not-a-heading" not in slugs
        assert "real-heading" in slugs
        assert "another" in slugs

    def test_valid_anchor(self):
        engine = make_engine(page_paths=["docs/page.md"])
        engine.heading_index["docs/page.md"] = ["intro", "setup", "faq"]
        is_valid, available = engine.validate_anchor("#setup", "docs/page.md")
        assert is_valid is True

    def test_invalid_anchor(self):
        engine = make_engine(page_paths=["docs/page.md"])
        engine.heading_index["docs/page.md"] = ["intro", "setup", "faq"]
        is_valid, available = engine.validate_anchor("#nonexistent", "docs/page.md")
        assert is_valid is False
        assert "intro" in available

    def test_empty_anchor_valid(self):
        engine = make_engine()
        is_valid, _ = engine.validate_anchor("", "docs/page.md")
        assert is_valid is True

    def test_hash_only_valid(self):
        engine = make_engine()
        is_valid, _ = engine.validate_anchor("#", "docs/page.md")
        assert is_valid is True

    def test_no_headings_considered_valid(self):
        """If we can't find any headings, we don't flag an error."""
        engine = make_engine()
        is_valid, _ = engine.validate_anchor("#something", "docs/page.md")
        assert is_valid is True

    def test_heading_with_inline_markup(self):
        md = "# **Bold** Heading\n## `Code` Here\n### [Link](url) Text"
        slugs = extract_heading_slugs(md)
        assert "bold-heading" in slugs
        assert "code-here" in slugs
        assert "link-text" in slugs

    def test_cache_current_page_headings(self):
        engine = make_engine()
        md = "# Title\n## Section One\n## Section Two"
        engine.cache_current_page_headings("docs/page.md", md)
        assert engine.heading_index["docs/page.md"] == [
            "title",
            "section-one",
            "section-two",
        ]

    def test_disk_read_caching(self):
        """Test that heading extraction from disk works and caches."""
        engine = make_engine()
        with tempfile.TemporaryDirectory() as tmpdir:
            md_path = os.path.join(tmpdir, "page.md")
            with open(md_path, "w") as f:
                f.write("# Disk Title\n## Disk Section\n")
            slugs = engine._get_heading_slugs("page.md", docs_dir=tmpdir)
            assert "disk-title" in slugs
            assert "disk-section" in slugs
            # Second call uses cache
            assert engine.heading_index["page.md"] == slugs


# ===========================================================================
# 6. Markdown replacement
# ===========================================================================


class TestMarkdownReplacement:
    def _resolve(self, markdown, page_paths=None, asset_paths=None,
                 current_page="docs/current.md"):
        engine = make_engine(page_paths=page_paths, asset_paths=asset_paths)
        page = make_page(current_page)
        config = {"docs_dir": "/nonexistent"}  # disable disk reads for anchor validation
        return engine.resolve_all_wiki_links(markdown, page, config, [])

    def test_page_link(self):
        result = self._resolve(
            "See [[setup]] for details.",
            page_paths=["docs/setup.md"],
        )
        assert "[Setup](setup.md)" in result
        assert "[[" not in result

    def test_page_link_with_display(self):
        result = self._resolve(
            "See [[setup|the guide]].",
            page_paths=["docs/setup.md"],
        )
        assert "[the guide](setup.md)" in result

    def test_image_embed(self):
        result = self._resolve(
            "![[diagram.png]]",
            asset_paths=["docs/diagram.png"],
        )
        assert "![Diagram](diagram.png)" in result

    def test_image_with_alt(self):
        result = self._resolve(
            "![[diagram.png|My Diagram]]",
            asset_paths=["docs/diagram.png"],
        )
        assert "![My Diagram](diagram.png)" in result

    def test_image_with_attrs(self):
        result = self._resolve(
            '![[diagram.png]]{: .center width="500"}',
            asset_paths=["docs/diagram.png"],
        )
        assert '{: .center width="500"}' in result

    def test_image_with_link_target(self):
        result = self._resolve(
            "![[logo.png]](:setup)",
            page_paths=["docs/setup.md"],
            asset_paths=["docs/logo.png"],
        )
        assert "setup.md" in result
        assert "logo.png" in result

    def test_code_fence_exclusion(self):
        md = "```\n[[setup]]\n```\n[[setup]]"
        result = self._resolve(md, page_paths=["docs/setup.md"])
        # The one inside the fence should remain as [[setup]]
        assert result.count("[[setup]]") == 1

    def test_inline_code_exclusion(self):
        md = "Use `[[setup]]` syntax. Also [[setup]]."
        result = self._resolve(md, page_paths=["docs/setup.md"])
        assert "`[[setup]]`" in result

    def test_error_span_for_unresolved(self):
        result = self._resolve("[[nonexistent]]", page_paths=["docs/setup.md"])
        assert "⚠" in result
        assert "color:red" in result

    def test_bare_anchor_link(self):
        result = self._resolve("[[#section]]", page_paths=["docs/setup.md"])
        assert "[section](#section)" in result

    def test_non_image_asset_download_link(self):
        result = self._resolve(
            "![[report.pdf]]",
            asset_paths=["docs/report.pdf"],
        )
        assert "[Report](report.pdf)" in result
        assert "![" not in result  # not an image embed

    def test_image_click_to_enlarge(self):
        """Images without (:link) get wrapped in a click-to-enlarge link."""
        result = self._resolve(
            "![[photo.png]]",
            asset_paths=["docs/photo.png"],
        )
        # Should be [![Photo](photo.png)](photo.png)
        assert "[![Photo](photo.png)](photo.png)" in result

    def test_external_link_target(self):
        result = self._resolve(
            "![[logo.png]](:https://example.com)",
            asset_paths=["docs/logo.png"],
        )
        assert "https://example.com" in result

    def test_anchor_validation_error_span(self):
        """Invalid anchor on a resolved page produces an error span."""
        engine = make_engine(page_paths=["docs/target.md"])
        engine.heading_index["docs/target.md"] = ["intro", "setup"]
        page = make_page("docs/current.md")
        config = {"docs_dir": "/nonexistent"}
        result = engine.resolve_all_wiki_links(
            "[[target#bad-heading]]", page, config, []
        )
        assert "⚠" in result
        assert "color:red" in result
        assert "not found" in result.lower()


# ===========================================================================
# 7. Quality checks
# ===========================================================================


class TestQualityChecks:
    def test_missing_h1(self):
        engine = make_engine()
        page = make_page("docs/page.md")
        warnings = engine.run_quality_checks("No heading here.", page)
        assert any("Missing top-level heading" in w for w in warnings)

    def test_stub_page(self):
        engine = make_engine()
        page = make_page("docs/page.md")
        warnings = engine.run_quality_checks("# Title\nShort.", page)
        assert any("Stub page" in w for w in warnings)

    def test_todo_markers(self):
        engine = make_engine()
        page = make_page("docs/page.md")
        md = "# Title\n" + "word " * 30 + "\nTODO fix this\nFIXME later"
        warnings = engine.run_quality_checks(md, page)
        assert any("markers" in w.lower() for w in warnings)

    def test_empty_admonition(self):
        engine = make_engine()
        page = make_page("docs/page.md")
        md = "# Title\n" + "word " * 30 + "\n!!!\n"
        warnings = engine.run_quality_checks(md, page)
        assert any("Empty admonition" in w for w in warnings)

    def test_no_warnings_for_good_page(self):
        engine = make_engine()
        page = make_page("docs/page.md")
        md = "# Good Page\n\n" + "This is a well-formed page with enough content. " * 5
        warnings = engine.run_quality_checks(md, page)
        assert len(warnings) == 0

    def test_page_title_captured(self):
        engine = make_engine()
        page = make_page("docs/page.md")
        engine.run_quality_checks("# My Page Title\n\n" + "word " * 30, page)
        assert engine.page_titles["docs/page.md"] == "My Page Title"

    def test_quality_issues_found_flag(self):
        engine = make_engine()
        page = make_page("docs/page.md")
        assert engine.quality_issues_found is False
        engine.run_quality_checks("No heading, short.", page)
        assert engine.quality_issues_found is True


# ===========================================================================
# 8. Legacy link detection
# ===========================================================================


class TestLegacyLinkDetection:
    def test_detects_internal_link(self):
        engine = make_engine(page_paths=["docs/setup.md", "docs/page.md"])
        page = make_page("docs/page.md")
        engine.check_legacy_links("[Setup](setup.md)", page)
        assert len(engine.legacy_link_report) == 1
        assert "[[setup]]" in engine.legacy_link_report[0].lower() or "[[Setup]]" in engine.legacy_link_report[0]

    def test_ignores_external_links(self):
        engine = make_engine(page_paths=["docs/page.md"])
        page = make_page("docs/page.md")
        engine.check_legacy_links("[Example](https://example.com)", page)
        assert len(engine.legacy_link_report) == 0

    def test_ignores_anchor_links(self):
        engine = make_engine(page_paths=["docs/page.md"])
        page = make_page("docs/page.md")
        engine.check_legacy_links("[Section](#section)", page)
        assert len(engine.legacy_link_report) == 0

    def test_ignores_code_blocks(self):
        engine = make_engine(page_paths=["docs/setup.md", "docs/page.md"])
        page = make_page("docs/page.md")
        md = "```\n[Setup](setup.md)\n```"
        engine.check_legacy_links(md, page)
        assert len(engine.legacy_link_report) == 0

    def test_asset_reference_tracked(self):
        engine = make_engine(
            page_paths=["docs/page.md"],
            asset_paths=["docs/diagram.png"],
        )
        page = make_page("docs/page.md")
        engine.check_legacy_links("![Diagram](diagram.png)", page)
        assert "docs/diagram.png" in engine.referenced_assets


# ===========================================================================
# 9. Auto-append
# ===========================================================================


class TestAutoAppend:
    def test_appends_content(self):
        engine = make_engine()
        with tempfile.TemporaryDirectory() as tmpdir:
            include_file = os.path.join(tmpdir, "footer.md")
            with open(include_file, "w") as f:
                f.write("---\nFooter content\n")
            engine.auto_append_files = ["footer.md"]
            engine.auto_append_base = [tmpdir]
            result = engine.expand_auto_append("# Page\n\nBody text.")
            assert "Footer content" in result

    def test_missing_file_warning(self, caplog):
        engine = make_engine()
        engine.auto_append_files = ["missing.md"]
        engine.auto_append_base = ["/nonexistent"]
        with caplog.at_level(logging.WARNING, logger="mkdocs.hooks"):
            engine.expand_auto_append("# Page")
        assert any("not found" in r.message for r in caplog.records)

    def test_blank_line_separation(self):
        engine = make_engine()
        with tempfile.TemporaryDirectory() as tmpdir:
            include_file = os.path.join(tmpdir, "extra.md")
            with open(include_file, "w") as f:
                f.write("Extra stuff\n")
            engine.auto_append_files = ["extra.md"]
            engine.auto_append_base = [tmpdir]
            result = engine.expand_auto_append("# Page\nNo trailing newlines")
            # Should have blank line before appended content
            assert "\n\nExtra stuff" in result


# ===========================================================================
# 10. Orphan asset detection
# ===========================================================================


class TestOrphanAssetDetection:
    def test_detects_orphans(self, caplog):
        engine = make_engine(asset_paths=["docs/used.png", "docs/unused.png"])
        engine.referenced_assets.add("docs/used.png")
        with caplog.at_level(logging.WARNING, logger="mkdocs.hooks"):
            engine.check_orphan_assets({})
        assert any("unreferenced" in r.message.lower() for r in caplog.records)
        assert any("unused.png" in r.message for r in caplog.records)

    def test_ignores_assets_dir(self, caplog):
        engine = make_engine(asset_paths=["assets/logo.png"])
        with caplog.at_level(logging.WARNING, logger="mkdocs.hooks"):
            engine.check_orphan_assets({})
        orphan_msgs = [r.message for r in caplog.records if "unreferenced" in r.message.lower()]
        assert len(orphan_msgs) == 0

    def test_no_orphans_no_warning(self, caplog):
        engine = make_engine(asset_paths=["docs/used.png"])
        engine.referenced_assets.add("docs/used.png")
        with caplog.at_level(logging.WARNING, logger="mkdocs.hooks"):
            engine.check_orphan_assets({})
        assert not any("unreferenced" in r.message.lower() for r in caplog.records)


# ===========================================================================
# 11. Code fence detection (unit tests for helper)
# ===========================================================================


class TestCodeFenceDetection:
    def test_fenced_code_block(self):
        md = "before\n```\ncode\n```\nafter"
        ranges = _strip_code_fences(md)
        assert len(ranges) >= 1
        # The code block range should cover "```\ncode\n```"
        assert _inside_code(md.index("code"), ranges)
        assert not _inside_code(0, ranges)

    def test_inline_code(self):
        md = "Use `some code` here"
        ranges = _strip_code_fences(md)
        assert _inside_code(md.index("some"), ranges)
        assert not _inside_code(0, ranges)

    def test_tilde_fence(self):
        md = "before\n~~~\ncode\n~~~\nafter"
        ranges = _strip_code_fences(md)
        assert _inside_code(md.index("code"), ranges)


# ===========================================================================
# 12. Shortest disambiguation (unified method)
# ===========================================================================


class TestShortestDisambiguation:
    def test_page_disambiguation(self):
        f1 = FakeFile(src_path="docs/a/setup.md")
        f2 = FakeFile(src_path="docs/b/setup.md")
        engine = make_engine()
        result = engine._shortest_disambiguation(
            f1, [f1, f2], WikiLinkEngine._page_parts
        )
        assert "a/setup" in result.lower()

    def test_asset_disambiguation(self):
        f1 = FakeFile(src_path="images/a/icon.svg")
        f2 = FakeFile(src_path="images/b/icon.svg")
        engine = make_engine()
        result = engine._shortest_disambiguation(
            f1, [f1, f2], WikiLinkEngine._asset_parts
        )
        assert "a/icon.svg" in result.lower()

    def test_index_page_disambiguation(self):
        f1 = FakeFile(src_path="docs/a/index.md")
        f2 = FakeFile(src_path="docs/b/index.md")
        engine = make_engine()
        result = engine._shortest_disambiguation(
            f1, [f1, f2], WikiLinkEngine._page_parts
        )
        assert "a" in result.lower()


# ===========================================================================
# 13. Engine re-creation on build
# ===========================================================================


class TestEngineLifecycle:
    def test_build_indexes_resets_state(self):
        engine = make_engine(page_paths=["docs/a.md"])
        engine.page_titles["docs/a.md"] = "Title A"
        engine.referenced_assets.add("img.png")
        engine.legacy_link_report.append("test")
        engine.heading_index["docs/a.md"] = ["heading"]

        engine.build_indexes([FakeFile(src_path="docs/b.md")])

        # page_titles accumulate across pages (populated by run_quality_checks),
        # so build_indexes does NOT clear them — this is by design.
        assert "docs/a.md" in engine.page_titles
        assert len(engine.referenced_assets) == 0
        assert len(engine.legacy_link_report) == 0
        assert len(engine.heading_index) == 0
        assert "a" not in engine.page_index_by_stem
        assert "b" in engine.page_index_by_stem
