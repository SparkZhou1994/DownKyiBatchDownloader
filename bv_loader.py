"""BV 号文件解析。

支持：
- 每行一个 BV 号或完整 B 站 URL（自动提取 BV）
- `#` 开头的注释
- 空行 / 纯空白
- 自动去重（保留首次出现顺序）
- 编码自动识别（utf-8-sig / utf-8 / gbk 兜底）
"""
from __future__ import annotations

import re
from pathlib import Path

# BV 号格式：BV + 10 个字母数字
BV_PATTERN = re.compile(r"BV[0-9A-Za-z]{10}")


class BvLoadError(Exception):
    """BV 号文件加载失败。"""


def _read_text(path: Path) -> str:
    """读取文件，依次尝试 utf-8-sig / utf-8 / gbk。"""
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    # 兜底：忽略错误
    return path.read_text(encoding="utf-8", errors="ignore")


def load_bv_list(path: Path) -> list[str]:
    """读取 BV 号文件，返回清洗后的 BV 号列表。

    规则：
    1. 文件不存在 → 抛 BvLoadError
    2. 去除空行、`#` 注释
    3. 逐行提取第一个 BV 号（兼容 URL/纯文本）
    4. 去重（保持首次出现顺序）
    5. 若最终无有效 BV → 抛 BvLoadError
    """
    if not path.exists():
        raise BvLoadError(f"BV 号文件不存在: {path}")

    text = _read_text(path).strip()
    if not text:
        raise BvLoadError(f"BV 号文件为空: {path}")

    seen: set[str] = set()
    result: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = BV_PATTERN.search(line)
        if not match:
            continue
        bvid = match.group(0)
        if bvid in seen:
            continue
        seen.add(bvid)
        result.append(bvid)

    if not result:
        raise BvLoadError(f"BV 号文件中没有有效的 BV 号: {path}")

    return result
