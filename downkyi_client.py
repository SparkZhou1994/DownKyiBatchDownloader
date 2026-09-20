"""DownKyi UI 自动化客户端（UIA 后端）。

封装对 DownKyi 1.6.1 主窗口的所有操作。每个方法职责单一、便于复用与测试。

设计原则：
- 通过 UIA（pywinauto uia 后端）操控 WPF 控件
- UIA Wrapper 没有 `child_window()` / `wait()`，改用 `descendants()` 遍历 + `timings.wait_until_passes` 轮询
- 控件查找优先用 `automation_id`（即 x:Name），其次用 `name`（即 Content/Text）
- 等待用 `wait_until_passes`（注意：它超时时返回 False 而不抛异常）
"""
from __future__ import annotations

import logging
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

from pywinauto import Application, timings
from pywinauto.findwindows import ElementNotFoundError

from config import (
    AUTO_ID_DETAIL_PAGES,
    AUTO_ID_INDEX_INPUT,
    BACK_TO_INDEX_TIMEOUT,
    CONNECT_TIMEOUT,
    CONTROL_TYPE_BUTTON,
    CONTROL_TYPE_CHECKBOX,
    CONTROL_TYPE_COMBOBOX,
    CONTROL_TYPE_DATAGRID,
    CONTROL_TYPE_EDIT,
    DETAIL_LOAD_TIMEOUT,
    PARSE_VIDEOS_TIMEOUT,
    PROCESS_NAME,
    SCREENSHOT_DIR,
    TEXT_BACK,
    TEXT_CANCEL,
    TEXT_DOWNLOAD,
    TEXT_DOWNLOAD_SELECTED,
    TEXT_OK,
    TEXT_PARSE_ALL,
    TEXT_PARSE_VIDEO,
    TEXT_SELECT_ALL,
    TEXT_SET_PARSE_DEFAULT,
)

logger = logging.getLogger(__name__)


class DownKyiError(Exception):
    """DownKyi 操作失败。"""


class DownKyiClient:
    """DownKyi 主窗口的 UI 自动化封装。

    真实手动流程：
        1. 首页输入框输 BV → Enter
        2. 详情页点"全选" + 点"解析视频"
        3. 等每个分P的画质/音质/编码 ComboBox 填充完
        4. 点"下载选中项" → 弹下载设置对话框
        5. 点"下载" → 加入下载队列
    """

    def __init__(self, screenshot_dir: Path = Path(SCREENSHOT_DIR)) -> None:
        self._app: Optional[Application] = None
        self._main = None
        self._screenshot_dir = screenshot_dir
        self._screenshot_dir.mkdir(parents=True, exist_ok=True)

    # ============================================================
    # 底层：控件查找 + 等待（UIA 兼容）
    # ============================================================

    def _iter_all_descendants(self):
        """迭代主窗口 + 所有顶级对话框窗口的 descendants。

        Prism Dialog Service 会创建独立顶级 Window（不是 main window 的 child），
        所以必须搜所有顶层窗口才能找到对话框里的控件。
        """
        if self._app is None:
            return
        seen_handles: set[int] = set()
        for win in self._app.windows():
            try:
                h = win.handle
            except Exception:
                continue
            if h in seen_handles:
                continue
            seen_handles.add(h)
            try:
                yield from win.descendants()
            except Exception:
                continue

    def _find_control(
        self,
        auto_id: Optional[str] = None,
        control_type: Optional[str] = None,
        name: Optional[str] = None,
        name_exact: bool = True,
    ):
        """在主窗口 + 所有顶级对话框的 descendants 中查找第一个匹配条件的控件。

        优先用 `element_info`（UIA 统一属性）兼容所有 Wrapper 子类。
        """
        try:
            for ctrl in self._iter_all_descendants():
                ei = ctrl.element_info
                if auto_id is not None and ei.automation_id != auto_id:
                    continue
                if control_type is not None and ei.control_type != control_type:
                    continue
                if name is not None:
                    ctrl_name = (ei.name or "")
                    if name_exact:
                        if ctrl_name != name:
                            continue
                    else:
                        if name not in ctrl_name:
                            continue
                return ctrl
        except Exception as e:  # noqa: BLE001
            logger.debug("_find_control 异常: %s", e)
        return None

    def _find_all(
        self,
        auto_id: Optional[str] = None,
        control_type: Optional[str] = None,
        name: Optional[str] = None,
        name_exact: bool = True,
    ) -> list:
        """查找所有匹配条件的控件（跨所有顶级窗口）。"""
        results = []
        try:
            for ctrl in self._iter_all_descendants():
                ei = ctrl.element_info
                if auto_id is not None and ei.automation_id != auto_id:
                    continue
                if control_type is not None and ei.control_type != control_type:
                    continue
                if name is not None:
                    ctrl_name = (ei.name or "")
                    if name_exact:
                        if ctrl_name != name:
                            continue
                    else:
                        if name not in ctrl_name:
                            continue
                results.append(ctrl)
        except Exception:  # noqa: BLE001
            pass
        return results

    def _wait_for_control(
        self,
        auto_id: Optional[str] = None,
        control_type: Optional[str] = None,
        name: Optional[str] = None,
        name_exact: bool = True,
        timeout: int = 10,
    ):
        """轮询直到控件出现（跨所有顶级窗口），返回控件或抛 DownKyiError。

        注意：pywinauto `wait_until_passes` 超时时返回 False 而不抛异常。
        """
        ctrl_box = [None]
        found = [False]

        def find():
            ctrl_box[0] = self._find_control(
                auto_id=auto_id,
                control_type=control_type,
                name=name,
                name_exact=name_exact,
            )
            if ctrl_box[0] is not None:
                found[0] = True
                return True
            return False

        timings.wait_until_passes(timeout, 0.2, find)

        if not found[0]:
            label = f"auto_id={auto_id!r} type={control_type!r} name={name!r}"
            raise DownKyiError(f"等待控件超时（{timeout}s）: {label}")

        return ctrl_box[0]

    def _control_exists(
        self,
        auto_id: Optional[str] = None,
        control_type: Optional[str] = None,
        name: Optional[str] = None,
        name_exact: bool = True,
        timeout: int = 2,
    ) -> bool:
        """判断控件是否存在。"""
        try:
            self._wait_for_control(
                auto_id=auto_id,
                control_type=control_type,
                name=name,
                name_exact=name_exact,
                timeout=timeout,
            )
            return True
        except DownKyiError:
            return False

    # ============================================================
    # 连接 / 窗口
    # ============================================================

    def connect(self, timeout: int = CONNECT_TIMEOUT) -> None:
        """连接到已启动的 DownKyi 主窗口。

        策略：按进程名/PID 连接（不依赖窗口标题，标题是"哔哩下载姬"）。
        """
        pid = self._find_downkyi_pid()
        if pid is None:
            raise DownKyiError(
                f"未找到运行中的 {PROCESS_NAME}.exe 进程，请先启动 DownKyi"
            )

        try:
            self._app = Application(backend="uia").connect(
                process=pid, timeout=timeout
            )
        except ElementNotFoundError as e:
            raise DownKyiError(
                f"连接 DownKyi 进程 {pid} 失败（{timeout}s 内）"
            ) from e

        candidates = self._app.windows()
        if not candidates:
            raise DownKyiError("DownKyi 窗口列表为空")
        self._main = candidates[0]

        logger.info(
            "已连接 DownKyi 主窗口: pid=%d title=%s",
            pid,
            self._main.window_text(),
        )

    @staticmethod
    def _find_downkyi_pid() -> int | None:
        """通过进程名查找 DownKyi.exe 的 PID。"""
        try:
            import psutil  # type: ignore
        except ImportError:
            psutil = None

        target = f"{PROCESS_NAME.lower()}.exe"

        if psutil is not None:
            for p in psutil.process_iter(["name"]):
                name = p.info["name"]
                if name and name.lower() == target:
                    return p.pid
            return None

        # 兜底：tasklist
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {PROCESS_NAME}.exe",
             "/NH", "/FO", "CSV"],
            capture_output=True, text=True,
        )
        for line in result.stdout.splitlines():
            if f"{PROCESS_NAME}.exe" in line:
                parts = line.split(",")
                if len(parts) >= 2:
                    try:
                        return int(parts[1].strip().strip('"'))
                    except ValueError:
                        continue
        return None

    def set_focus(self) -> None:
        """把 DownKyi 窗口置前。"""
        if self._main is None:
            return
        try:
            self._main.set_focus()
        except Exception as e:  # noqa: BLE001
            logger.warning("set_focus 失败: %s", e)

    def screenshot(self, name: str) -> Optional[Path]:
        """保存当前主窗口截图。"""
        if self._main is None:
            return None
        try:
            path = self._screenshot_dir / f"{name}.png"
            self._main.capture_as_image().save(str(path))
            return path
        except Exception as e:  # noqa: BLE001
            logger.warning("截图失败 %s: %s", name, e)
            return None

    # ============================================================
    # 等待页面
    # ============================================================

    def wait_for_index_page(self, timeout: int = 30) -> None:
        """等待首页 `nameInputUrl` 输入框可见。"""
        self._wait_for_control(
            auto_id=AUTO_ID_INDEX_INPUT,
            control_type=CONTROL_TYPE_EDIT,
            timeout=timeout,
        )

    def wait_for_detail_page(self, timeout: int = DETAIL_LOAD_TIMEOUT) -> None:
        """等待视频详情页 `nameVideoPages` 出现。"""
        try:
            self._wait_for_control(
                auto_id=AUTO_ID_DETAIL_PAGES,
                control_type=CONTROL_TYPE_DATAGRID,
                timeout=timeout,
            )
        except DownKyiError:
            self.screenshot("detail_timeout")
            raise

    def is_on_index_page(self, timeout: int = 2) -> bool:
        """判断是否在首页。"""
        return self._control_exists(
            auto_id=AUTO_ID_INDEX_INPUT,
            control_type=CONTROL_TYPE_EDIT,
            timeout=timeout,
        )

    # ============================================================
    # 输入 BV 并触发解析
    # ============================================================

    def input_bv_and_parse(self, bvid: str) -> None:
        """把 BV 号输入首页输入框并按 Enter 触发 InputCommand。"""
        if not re.match(r"^BV[0-9A-Za-z]{10}$", bvid):
            raise DownKyiError(f"BV 号格式不合法: {bvid}")

        self.set_focus()
        input_box = self._wait_for_control(
            auto_id=AUTO_ID_INDEX_INPUT,
            control_type=CONTROL_TYPE_EDIT,
            timeout=10,
        )

        try:
            input_box.set_edit_text("")
        except Exception:  # noqa: BLE001
            try:
                input_box.type_keys("^a{DEL}", set_foreground=False)
            except Exception:
                pass
        input_box.type_keys(bvid, set_foreground=False)
        input_box.type_keys("{ENTER}", set_foreground=False)
        logger.info("已提交 BV: %s", bvid)

    # ============================================================
    # 视频详情页操作（真实手动流程）
    # ============================================================

    def click_select_all(self, timeout: int = 10) -> None:
        """勾选详情页底部的"全选" CheckBox（用鼠标坐标点击）。"""
        from pywinauto import mouse  # type: ignore

        chk = self._wait_for_control(
            name=TEXT_SELECT_ALL,
            control_type=CONTROL_TYPE_CHECKBOX,
            timeout=timeout,
        )
        rect = chk.element_info.rectangle
        if not rect or rect.width() <= 0:
            raise DownKyiError("全选 CheckBox 位置无效")

        # 记录点击前的状态
        before = chk.get_toggle_state()

        cx = (rect.left + rect.right) // 2
        cy = (rect.top + rect.bottom) // 2
        mouse.click(coords=(cx, cy))
        logger.info(
            "已鼠标点击全选（%d,%d）前状态=%d", cx, cy, before
        )

        time.sleep(0.5)
        # 验证勾选状态
        after = chk.get_toggle_state()
        logger.info("全选点击后状态=%d", after)
        if after == 0:
            logger.warning("全选点击后状态仍为 0，可能没生效")

        self._wait_for_selection_visible(timeout=10)

    def _focus_video_sections(self) -> None:
        """让 nameVideoSections ListBox 获得焦点 + SelectedItem 非 null。

        单 P 视频可能没有 nameVideoSections（Count=0 时整个控件隐藏），
        此时直接跳过。分 P 视频必须先点 ListItem 才能让 SelectAllCommand
        的 CommandParameter 有值。
        """
        from pywinauto import mouse  # type: ignore

        # 找 ListBox 的 ListItem
        for ctrl in self._iter_all_descendants():
            try:
                if (
                    ctrl.element_info.control_type == "ListItem"
                    and ctrl.element_info.automation_id == ""
                ):
                    # 方案 1：调用 select() 让它成为 SelectedItem
                    try:
                        ctrl.select()
                        logger.info("已选中分P列表的第一项（select）")
                        time.sleep(0.5)
                        return
                    except Exception:  # noqa: BLE001
                        pass

                    # 方案 2：物理点击 ListItem 中央
                    try:
                        rect = ctrl.element_info.rectangle
                        if rect and rect.width() > 0 and rect.height() > 0:
                            cx = (rect.left + rect.right) // 2
                            cy = (rect.top + rect.bottom) // 2
                            mouse.click(coords=(cx, cy))
                            logger.info("已点击分P列表项（%d,%d）", cx, cy)
                            time.sleep(0.5)
                            return
                    except Exception:  # noqa: BLE001
                        continue
            except Exception:  # noqa: BLE001
                continue
        logger.info("未找到分P列表项（可能是单 P 视频）")

    def _wait_for_selection_visible(self, timeout: int = 10) -> None:
        """轮询直到至少 1 个 DataItem 处于 IsSelected=True 状态。

        反映了 WPF DataGrid 行从白底变蓝底的视觉变化。
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            data_items = [
                c for c in self._iter_all_descendants()
                if c.element_info.control_type == "DataItem"
            ]
            if data_items:
                # 任一 DataItem 选中即视为生效
                for item in data_items:
                    try:
                        if item.is_selected():
                            logger.info(
                                "选中状态已生效（%d 个 DataItem）", len(data_items)
                            )
                            time.sleep(0.5)  # 缓冲
                            return
                    except Exception:  # noqa: BLE001
                        continue
            time.sleep(0.3)
        # 超时：可能单 P 视频无 DataItem 列表行，降级处理
        logger.warning("等待选中状态生效超时（%ds），降级 sleep 2s", timeout)
        time.sleep(2.0)

    def _wait_for_data_items(self, timeout: int = 15) -> None:
        """等 DataGrid 真的渲染出 DataItem（ItemsSource 异步绑定）。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            data_items = [
                c for c in self._iter_all_descendants()
                if c.element_info.control_type == "DataItem"
            ]
            if data_items:
                logger.info("详情页分P已渲染（%d 个 DataItem）", len(data_items))
                time.sleep(0.5)
                return
            time.sleep(0.5)
        logger.warning("等 DataItem 超时（%ds），可能详情页未正常加载", timeout)

    def click_parse_video(self, timeout: int = 10) -> None:
        """点击详情页的"解析视频"按钮（解析每个分P的画质/音质/编码）。

        用**鼠标坐标点击**（不是 UIA invoke），更可靠。
        注意：如果用户在 DownKyi 设置里没有"解析范围"（ParseScope.NOT_SET），
        点击此按钮会**弹 ViewParsingSelector 对话框**让用户选范围，
        需要后续调用 `select_parse_all_and_default()` 处理。
        """
        from pywinauto import mouse  # type: ignore

        btn = self._wait_for_control(
            name=TEXT_PARSE_VIDEO,
            control_type=CONTROL_TYPE_BUTTON,
            timeout=timeout,
        )
        rect = btn.element_info.rectangle
        if not rect or rect.width() <= 0:
            raise DownKyiError("解析视频按钮位置无效")
        cx = (rect.left + rect.right) // 2
        cy = (rect.top + rect.bottom) // 2
        mouse.click(coords=(cx, cy))
        logger.info("已鼠标点击『%s』（%d,%d）", TEXT_PARSE_VIDEO, cx, cy)
        # 给 UI 时间启动解析（Command 内部 await Task.Run）
        time.sleep(2.0)

    def in_parsing_selector_dialog(self, timeout: int = 3) -> bool:
        """检测是否弹出 ViewParsingSelector 清晰度/解析范围选择对话框。"""
        return self._control_exists(
            name=TEXT_PARSE_ALL,
            control_type=CONTROL_TYPE_BUTTON,
            timeout=timeout,
        )

    def select_parse_all_and_default(self, timeout: int = 10) -> None:
        """在 ViewParsingSelector 对话框中：勾选"设为默认" + 点"全部解析"。"""
        # 1. 勾选"设为默认"（下次点"解析视频"就不弹这个对话框了）
        try:
            chk = self._wait_for_control(
                name=TEXT_SET_PARSE_DEFAULT,
                control_type=CONTROL_TYPE_CHECKBOX,
                timeout=timeout,
            )
            if chk.get_toggle_state() != 1:
                chk.toggle()
            logger.info("已勾选『%s』", TEXT_SET_PARSE_DEFAULT)
        except DownKyiError:
            logger.warning("未找到『%s』复选框", TEXT_SET_PARSE_DEFAULT)
        time.sleep(0.5)

        # 2. 点"全部解析"
        btn = self._wait_for_control(
            name=TEXT_PARSE_ALL,
            control_type=CONTROL_TYPE_BUTTON,
            timeout=timeout,
        )
        btn.invoke()
        logger.info("已点击『%s』按钮", TEXT_PARSE_ALL)
        # 解析是异步的（Command 内部 await Task.Run），等启动
        time.sleep(1.5)

    def wait_for_parsed_videos(self, timeout: int = PARSE_VIDEOS_TIMEOUT) -> None:
        """等分P的 ComboBox 填充（宽松策略）。

        不再死等全部填充。最多等 30s：
        - 5s 内至少出现 1 个 DataItem（说明详情页加载完成）
        - 然后再等 25s 让 ComboBox 尽可能填充
        - 超时后不抛异常，只记录警告，继续点"下载选中项"
        - DownKyi 自己会在后台继续解析失败的项
        """
        deadline = time.time() + min(timeout, 30)

        # 阶段 1：等 DataItem 出现（最多 5s）
        data_items_deadline = time.time() + 5
        while time.time() < data_items_deadline:
            data_items = [
                c for c in self._iter_all_descendants()
                if c.element_info.control_type == "DataItem"
            ]
            if data_items:
                logger.info("分P行已渲染（%d 个 DataItem）", len(data_items))
                break
            time.sleep(0.3)
        else:
            logger.warning("DataItem 未在 5s 内出现，详情页可能未正常加载")

        # 阶段 2：宽松等待 ComboBox 填充
        while time.time() < deadline:
            comboboxes = self._find_all(control_type=CONTROL_TYPE_COMBOBOX)
            count = len(comboboxes)
            if count > 0:
                filled = sum(
                    1 for cb in comboboxes
                    if (cb.window_text() or "").strip()
                    or (cb.element_info.name or "").strip()
                )
                elapsed = min(timeout, 30) - (deadline - time.time())
                logger.info(
                    "  等待中 ComboBox=%d 已填=%d 已等%.0fs",
                    count, filled, elapsed,
                )
                if filled == count and count > 0:
                    logger.info("所有 ComboBox 已填充")
                    return
            time.sleep(1.0)

        # 超时：警告 + 返回（不抛异常，让流程继续）
        comboboxes = self._find_all(control_type=CONTROL_TYPE_COMBOBOX)
        filled = sum(
            1 for cb in comboboxes
            if (cb.window_text() or "").strip()
            or (cb.element_info.name or "").strip()
        )
        logger.warning(
            "ComboBox 填充超时（%ds），继续点下载：%d/%d 已填",
            min(timeout, 30), filled, len(comboboxes),
        )

    def click_download_selected(self, timeout: int = 10) -> None:
        """点击详情页的"下载选中项"按钮（用鼠标坐标点击）。"""
        from pywinauto import mouse  # type: ignore

        btn = self._wait_for_control(
            name=TEXT_DOWNLOAD_SELECTED,
            control_type=CONTROL_TYPE_BUTTON,
            timeout=timeout,
        )
        rect = btn.element_info.rectangle
        if not rect or rect.width() <= 0:
            raise DownKyiError("下载选中项按钮位置无效")
        cx = (rect.left + rect.right) // 2
        cy = (rect.top + rect.bottom) // 2
        mouse.click(coords=(cx, cy))
        logger.info("已鼠标点击『%s』（%d,%d）", TEXT_DOWNLOAD_SELECTED, cx, cy)

    def click_back(self, timeout: int = 10) -> None:
        """从视频详情页返回首页。

        详情页"返回"按钮是图标按钮（无 name/auto_id），
        用位置策略找最左上角的 Button（Grid.Column=0，Margin=10,5）。
        过滤掉 width=0/height=0 的隐藏 Button。
        """
        # 方案 1：按 name 找（如果 DownKyi 升级给按钮加了文字）
        btn = self._find_control(
            name=TEXT_BACK, control_type=CONTROL_TYPE_BUTTON
        )
        if btn is not None:
            btn.invoke()
            logger.info("已点击『%s』按钮", TEXT_BACK)
            return

        # 方案 2：位置策略——找所有可见 Button，按 rectangle 排序，最左上角的
        # 即"返回"按钮（Grid.Column=0, Margin="10,5", Width=24, Height=24）
        candidates: list[tuple[int, int, int, object]] = []
        for ctrl in self._main.descendants():
            if ctrl.element_info.control_type != CONTROL_TYPE_BUTTON:
                continue
            try:
                rect = ctrl.element_info.rectangle
            except Exception:
                continue
            if rect is None:
                continue
            # 过滤掉不可见/未渲染的（width=0 或 height=0）
            if rect.width() <= 0 or rect.height() <= 0:
                continue
            candidates.append((rect.left, rect.top, rect.width() * rect.height(), ctrl))

        if not candidates:
            raise DownKyiError("找不到任何可见的 Button 控件")

        # 按 (left, top) 排序——最左上角的就是返回按钮
        candidates.sort()
        back_btn = candidates[0][3]
        try:
            back_btn.invoke()
            logger.info(
                "已点击最左上角 Button（位置 %d,%d, 面积 %d）作为返回",
                candidates[0][0], candidates[0][1], candidates[0][2],
            )
        except Exception as e:  # noqa: BLE001
            raise DownKyiError(f"点击返回按钮失败: {e}")

    def wait_until_back_on_index(self, timeout: int = BACK_TO_INDEX_TIMEOUT) -> None:
        """等待回到首页。"""
        self.wait_for_index_page(timeout=timeout)

    # ============================================================
    # 下载设置对话框
    # ============================================================

    def in_download_setter_dialog(self, timeout: int = 3) -> bool:
        """检测是否弹出 ViewDownloadSetter 下载设置对话框。"""
        return self._control_exists(
            name=TEXT_DOWNLOAD, control_type=CONTROL_TYPE_BUTTON, timeout=timeout
        )

    def click_download_button(self, timeout: int = 10) -> None:
        """在下载设置对话框中点"下载"按钮（鼠标坐标点击）。"""
        from pywinauto import mouse  # type: ignore

        btn = self._wait_for_control(
            name=TEXT_DOWNLOAD, control_type=CONTROL_TYPE_BUTTON, timeout=timeout
        )
        rect = btn.element_info.rectangle
        if not rect or rect.width() <= 0:
            raise DownKyiError("下载按钮位置无效")
        cx = (rect.left + rect.right) // 2
        cy = (rect.top + rect.bottom) // 2
        mouse.click(coords=(cx, cy))
        logger.info("已鼠标点击『%s』（%d,%d）", TEXT_DOWNLOAD, cx, cy)

    def click_cancel_button(self, timeout: int = 10) -> None:
        """在下载设置对话框中点"取消"按钮（失败回滚用）。"""
        try:
            btn = self._wait_for_control(
                name=TEXT_CANCEL, control_type=CONTROL_TYPE_BUTTON, timeout=timeout
            )
            btn.invoke()
            logger.info("已点击『%s』按钮", TEXT_CANCEL)
        except DownKyiError:
            logger.warning("未找到『%s』按钮，跳过", TEXT_CANCEL)

    # ============================================================
    # 错误弹窗处理
    # ============================================================

    def dismiss_alert_if_any(self) -> bool:
        """捕获并关闭可能的错误弹窗（ViewAlertDialog）。"""
        if self._main is None:
            return False
        ok = self._find_control(name=TEXT_OK, control_type=CONTROL_TYPE_BUTTON)
        if ok is not None:
            try:
                ok.invoke()
                logger.info("已关闭错误弹窗")
                return True
            except Exception as e:  # noqa: BLE001
                logger.debug("关闭错误弹窗失败: %s", e)
        return False

    # ============================================================
    # 进程相关
    # ============================================================

    @staticmethod
    def is_process_running() -> bool:
        """DownKyi 进程是否在运行。"""
        return DownKyiClient._find_downkyi_pid() is not None

    @staticmethod
    def start_process(exe_path: Path) -> None:
        """启动 DownKyi.exe。"""
        if not exe_path.exists():
            raise DownKyiError(f"DownKyi.exe 不存在: {exe_path}")
        subprocess.Popen(
            [str(exe_path)],
            cwd=str(exe_path.parent),
            creationflags=0x00000008,  # DETACHED_PROCESS
        )
