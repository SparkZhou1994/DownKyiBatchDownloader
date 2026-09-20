"""bv_loader 的单元测试。

按 TDD 流程：先写失败测试，再实现函数。
"""
from pathlib import Path

import pytest

from bv_loader import BvLoadError, load_bv_list


class TestLoadBvListNormal:
    """正常情况：每行一个标准 BV 号。"""

    def test_single_bv(self, tmp_path: Path):
        p = tmp_path / "bvs.txt"
        p.write_text("BV1xx411c7mD\n", encoding="utf-8")
        assert load_bv_list(p) == ["BV1xx411c7mD"]

    def test_multiple_bvs(self, tmp_path: Path):
        p = tmp_path / "bvs.txt"
        p.write_text(
            "BV1xx411c7mD\nBV2yy522d8nE\nBV3zz633e9oF\n",
            encoding="utf-8",
        )
        assert load_bv_list(p) == [
            "BV1xx411c7mD",
            "BV2yy522d8nE",
            "BV3zz633e9oF",
        ]

    def test_preserves_order(self, tmp_path: Path):
        p = tmp_path / "bvs.txt"
        p.write_text(
            "BV1zz1111aa1\nBV1aa2222bb2\nBV1mm3333cc3\n",
            encoding="utf-8",
        )
        assert load_bv_list(p) == ["BV1zz1111aa1", "BV1aa2222bb2", "BV1mm3333cc3"]


class TestLoadBvListUrlExtraction:
    """容错：用户可能复制完整 URL。"""

    def test_extracts_bv_from_full_url(self, tmp_path: Path):
        p = tmp_path / "bvs.txt"
        p.write_text(
            "https://www.bilibili.com/video/BV1xx411c7mD?p=1\n",
            encoding="utf-8",
        )
        assert load_bv_list(p) == ["BV1xx411c7mD"]

    def test_extracts_bv_from_short_url(self, tmp_path: Path):
        p = tmp_path / "bvs.txt"
        p.write_text("https://b23.tv/BV1xx411c7mD\n", encoding="utf-8")
        assert load_bv_list(p) == ["BV1xx411c7mD"]

    def test_mixed_bv_and_url(self, tmp_path: Path):
        p = tmp_path / "bvs.txt"
        p.write_text(
            "BV1xx411c7mD\n"
            "https://www.bilibili.com/video/BV2yy522d8nE\n"
            "BV3zz633e9oF\n",
            encoding="utf-8",
        )
        assert load_bv_list(p) == [
            "BV1xx411c7mD",
            "BV2yy522d8nE",
            "BV3zz633e9oF",
        ]


class TestLoadBvListSkip:
    """跳过：空行、注释、纯空白。"""

    def test_skips_empty_lines(self, tmp_path: Path):
        p = tmp_path / "bvs.txt"
        p.write_text(
            "BV1xx411c7mD\n"
            "\n"
            "   \n"
            "BV2yy522d8nE\n",
            encoding="utf-8",
        )
        assert load_bv_list(p) == ["BV1xx411c7mD", "BV2yy522d8nE"]

    def test_skips_hash_comments(self, tmp_path: Path):
        p = tmp_path / "bvs.txt"
        p.write_text(
            "# 这是注释\n"
            "BV1xx411c7mD\n"
            "# 另一个注释\n"
            "BV2yy522d8nE\n",
            encoding="utf-8",
        )
        assert load_bv_list(p) == ["BV1xx411c7mD", "BV2yy522d8nE"]

    def test_trims_whitespace(self, tmp_path: Path):
        p = tmp_path / "bvs.txt"
        p.write_text("  BV1xx411c7mD  \n", encoding="utf-8")
        assert load_bv_list(p) == ["BV1xx411c7mD"]

    def test_dedup_preserves_first_occurrence(self, tmp_path: Path):
        p = tmp_path / "bvs.txt"
        p.write_text(
            "BV1xx411c7mD\nBV1xx411c7mD\nBV2yy522d8nE\n",
            encoding="utf-8",
        )
        assert load_bv_list(p) == ["BV1xx411c7mD", "BV2yy522d8nE"]


class TestLoadBvListInvalid:
    """错误情况：文件不存在、为空、无有效 BV。"""

    def test_file_not_found(self, tmp_path: Path):
        p = tmp_path / "missing.txt"
        with pytest.raises(BvLoadError, match="文件不存在"):
            load_bv_list(p)

    def test_empty_file(self, tmp_path: Path):
        p = tmp_path / "empty.txt"
        p.write_text("", encoding="utf-8")
        with pytest.raises(BvLoadError, match="为空"):
            load_bv_list(p)

    def test_only_comments_and_blank(self, tmp_path: Path):
        p = tmp_path / "no_bv.txt"
        p.write_text("# 注释\n\n   \n# 另一个\n", encoding="utf-8")
        with pytest.raises(BvLoadError, match="没有有效的 BV 号"):
            load_bv_list(p)

    def test_invalid_format_only(self, tmp_path: Path):
        p = tmp_path / "garbage.txt"
        p.write_text("not a bv\nhello world\n", encoding="utf-8")
        with pytest.raises(BvLoadError, match="没有有效的 BV 号"):
            load_bv_list(p)
