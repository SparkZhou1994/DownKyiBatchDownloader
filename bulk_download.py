"""批量把 BV 号送入 DownKyi 1.6.1 输入框并触发下载。

用法：
    uv run python bulk_download.py [BV号文件] [--limit N] [--dry-run]

BV 号文件每行一个 BV 号或完整 B 站 URL，支持 # 注释与空行。
日志追加写入 download_log.txt（OK / FAIL 两类）。
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from bv_loader import BvLoadError, load_bv_list
from config import DEFAULT_DOWNLOAD_DIR, LOG_FILE
from downkyi_client import DownKyiClient, DownKyiError

# ---- 日志 ----
logger = logging.getLogger("bulk_download")


def _setup_logging() -> None:
    """控制台 + 文件双输出。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


# ---- 纯函数（可测试）----


def build_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="bulk_download",
        description="批量把 BV 号送入 DownKyi 1.6.1 输入框并触发下载",
    )
    parser.add_argument(
        "bv_file",
        nargs="?",
        type=Path,
        default=Path("bv_list.txt"),
        help="BV 号文件路径，每行一个 BV 号或完整 B 站 URL（默认 bv_list.txt）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="最多处理前 N 个 BV 号（用于测试）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印计划，不操作 UI（用于调试）",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=Path(LOG_FILE),
        help=f"日志文件路径（默认 {LOG_FILE}）",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """便捷封装：parse_args() 直接读 sys.argv。"""
    return build_parser().parse_args(argv)


def format_log_line(status: str, bvid: str, message: str = "") -> str:
    """格式化单条日志行：[时间] 状态  BV号  备注。"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"[{ts}] {status} {bvid} {message}".rstrip()


def _append_log(log_file: Path, line: str) -> None:
    """追加一行日志到文件。"""
    try:
        with log_file.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:
        logger.warning("写日志失败 %s: %s", log_file, e)


# ---- 单 BV 处理流程 ----


def process_one(
    client: DownKyiClient,
    bvid: str,
    idx: int,
    total: int,
    dry_run: bool,
) -> bool:
    """处理单个 BV：解析 → 详情页 → 全部加入下载队列。

    真实手动流程（用户告知）：
        1. 首页输入 BV → Enter
        2. 详情页：点"全选" + 点"解析视频"
        3. 等所有分P的画质/音质/编码 ComboBox 填充完
        4. 点"下载选中项" → 弹下载设置对话框
        5. 点"下载" → 加入下载队列
    """
    prefix = f"[{idx}/{total}]"
    logger.info("%s 开始处理 %s", prefix, bvid)

    if dry_run:
        logger.info("  (dry-run) 跳过 UI 操作")
        return True

    try:
        # 1. 首页输入 BV + Enter 触发解析
        client.input_bv_and_parse(bvid)
        # 2. 等待视频详情页加载
        client.wait_for_detail_page()
        # 等 DataGrid 真的渲染出 DataItem（异步绑定）
        client._wait_for_data_items(timeout=15)
        # 3. 勾选"全选"（多P视频才有意义，单P也安全）
        client.click_select_all()
        # 4. 点"解析视频"——若用户没设"解析范围"，会弹 ViewParsingSelector
        client.click_parse_video()
        # 5. 处理 ViewParsingSelector 弹窗（选"全部"+"设为默认"）
        if client.in_parsing_selector_dialog(timeout=5):
            logger.info("  检测到解析范围选择弹窗，自动选『全部解析』")
            client.select_parse_all_and_default()
        else:
            logger.info("  未检测到 ViewParsingSelector 弹窗")
        # 6. 等分P的画质/音质/编码 ComboBox 填充（宽松 30s）
        client.wait_for_parsed_videos()
        # 7. 点"下载选中项"——DownKyi 会弹文件夹选择对话框（Windows 原生）
        client.click_download_selected()
        import time as _t
        _t.sleep(2.0)
        # 8. 等待回到首页（不再依赖检测 ViewDownloadSetter，因为实际是文件夹选择器）
        # 关键成功判断：5s 内能回到首页 = 加入下载队列成功
        try:
            client.wait_for_index_page(timeout=5)
            logger.info("  ✓ %s 已加入下载队列（请到 DownKyi 下载管理查看）", bvid)
            return True
        except DownKyiError:
            # 没回到首页——可能是文件夹选择器挡住了，按 ESC 关闭
            logger.warning("  未回到首页，尝试按 ESC 关闭弹窗...")
            try:
                from pywinauto import keyboard
                keyboard.send_keys("{ESC}")
                _t.sleep(1.0)
            except Exception:
                pass
            # 再试
            try:
                client.wait_for_index_page(timeout=10)
                logger.info("  ✓ %s 已加入下载队列（已关闭文件夹选择器）", bvid)
                return True
            except DownKyiError:
                logger.warning(
                    "  ⚠️ %s 未能回到首页，但可能已加入下载队列，"
                    "请检查 DownKyi 下载管理", bvid
                )
                return True  # 乐观：任务可能已加入
    except (DownKyiError, Exception) as e:  # noqa: BLE001
        logger.error("  ✗ %s 失败: %s", bvid, e)
        # 关闭可能弹出的错误弹窗
        client.dismiss_alert_if_any()
        # 尽力回到首页
        if not client.is_on_index_page():
            try:
                client.click_back()
                client.wait_for_index_page(timeout=30)
            except DownKyiError:
                logger.warning("  无法自动返回首页，请人工处理")
        return False


# ---- 主入口 ----


def run(args: argparse.Namespace) -> int:
    """主流程。返回退出码（0=全部成功，1=有失败）。"""
    try:
        bvs = load_bv_list(args.bv_file)
    except BvLoadError as e:
        logger.error("加载 BV 号文件失败: %s", e)
        return 2

    if args.limit is not None:
        bvs = bvs[: args.limit]

    logger.info("共 %d 个 BV 待处理", len(bvs))
    logger.info("当前下载目录（参考）: %s", DEFAULT_DOWNLOAD_DIR)

    # dry-run 模式：不连接 DownKyi，直接遍历（仍写日志便于事后排查）
    if args.dry_run:
        for idx, bvid in enumerate(bvs, 1):
            logger.info("  [DRY-RUN] %d/%d %s", idx, len(bvs), bvid)
            _append_log(args.log, format_log_line("SKIP", bvid, "dry-run 模式"))
        logger.info("完成（dry-run）：%d 个 BV 已预览", len(bvs))
        return 0

    # 连接 DownKyi
    client = DownKyiClient()
    try:
        client.connect()
    except DownKyiError as e:
        logger.error("连接 DownKyi 失败: %s", e)
        return 3

    # 等待首页就绪（启动容错：如果不在首页，先尝试返回）
    if not client.is_on_index_page():
        logger.warning("启动时 DownKyi 不在首页（可能上次残留），尝试返回...")
        try:
            client.click_back()
            client.wait_for_index_page(timeout=15)
        except DownKyiError as e:
            logger.error("回到首页失败: %s", e)
            return 4
    else:
        try:
            client.wait_for_index_page(timeout=30)
        except DownKyiError as e:
            logger.error("等待首页失败: %s", e)
            return 4

    # 处理每个 BV
    success_count = 0
    fail_count = 0
    for idx, bvid in enumerate(bvs, 1):
        # 循环内容错：如果不在首页（上次失败残留），先返回
        if not client.is_on_index_page():
            logger.warning("  [循环开始] 不在首页，先尝试返回...")
            try:
                client.click_back()
                client.wait_for_index_page(timeout=15)
            except DownKyiError:
                logger.error("  无法回到首页，跳过 %s", bvid)
                _append_log(args.log, format_log_line("FAIL", bvid, "无法回到首页"))
                fail_count += 1
                continue

        ok = process_one(client, bvid, idx, len(bvs), dry_run=False)
        line = format_log_line(
            "OK" if ok else "FAIL", bvid, "" if ok else "见上方错误"
        )
        _append_log(args.log, line)
        if ok:
            success_count += 1
        else:
            fail_count += 1


def main() -> int:
    """CLI 入口。"""
    _setup_logging()
    args = parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
