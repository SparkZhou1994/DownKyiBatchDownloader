"""bulk_download 的单元测试。

只测纯函数（参数解析、--dry-run 行为），不测 UI 交互部分。
"""
import argparse
import sys
from pathlib import Path

import pytest

from bulk_download import build_parser, format_log_line, parse_args


class TestBuildParser:
    """CLI 参数解析。"""

    def test_default_args(self):
        parser = build_parser()
        args = parser.parse_args([])
        assert args.bv_file == Path("bv_list.txt")
        assert args.limit is None
        assert args.dry_run is False

    def test_custom_bv_file(self):
        parser = build_parser()
        args = parser.parse_args(["my_bvs.txt"])
        assert args.bv_file == Path("my_bvs.txt")

    def test_limit(self):
        parser = build_parser()
        args = parser.parse_args(["bv_list.txt", "--limit", "5"])
        assert args.limit == 5

    def test_dry_run(self):
        parser = build_parser()
        args = parser.parse_args(["--dry-run"])
        assert args.dry_run is True


class TestFormatLogLine:
    """日志行格式。"""

    def test_success(self):
        line = format_log_line("OK", "BV1xx411c7mD", "已加入下载队列")
        assert line.startswith("[")
        assert "OK" in line
        assert "BV1xx411c7mD" in line
        assert "已加入下载队列" in line

    def test_failure(self):
        line = format_log_line("FAIL", "BV1xx411c7mD", "等待详情页超时")
        assert "FAIL" in line
        assert "等待详情页超时" in line


class TestParseArgs:
    """parse_args 便捷函数（异常 → 系统退出）。"""

    def test_valid_args(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["bulk_download.py", "bv_list.txt"])
        args = parse_args()
        assert args.bv_file == Path("bv_list.txt")

    def test_help_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["bulk_download.py", "--help"])
        with pytest.raises(SystemExit):
            parse_args()
