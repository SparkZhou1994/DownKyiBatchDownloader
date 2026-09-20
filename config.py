"""常量与控件 ID 集中管理。

任何 UI 控件 ID、文本、超时阈值都集中在这里。DownKyi 升级时只需要改这一处。
"""

# ---- 进程与窗口识别 ----
WINDOW_TITLE_RE = r"DownKyi"
PROCESS_NAME = "DownKyi"
CONNECT_TIMEOUT = 10  # 秒，等待 DownKyi 启动

# ---- 页面加载超时 ----
PAGE_LOAD_TIMEOUT = 60           # 视频详情页加载（包含网络请求）
DETAIL_LOAD_TIMEOUT = 60         # 同上（向后兼容别名）
BACK_TO_INDEX_TIMEOUT = 120      # 返回首页后等待
PARSE_VIDEOS_TIMEOUT = 180       # 等每个分P 画质/音质/编码解析完成

# ---- 控件 AutomationId（即 XAML x:Name）----
# WPF 应用通过 UIA 暴露 auto_id，对应 x:Name
AUTO_ID_INDEX_INPUT = "nameInputUrl"
AUTO_ID_DETAIL_PAGES = "nameVideoPages"
AUTO_ID_DETAIL_SECTIONS = "nameVideoSections"  # 分区 ListBox，分段视频才有

# ---- 控件 ControlType（WPF→UIA 映射）----
# ListView → DataGrid, TextBox → Edit, Button → Button, CheckBox → CheckBox
CONTROL_TYPE_EDIT = "Edit"
CONTROL_TYPE_DATAGRID = "DataGrid"
CONTROL_TYPE_LIST = "List"
CONTROL_TYPE_BUTTON = "Button"
CONTROL_TYPE_CHECKBOX = "CheckBox"
CONTROL_TYPE_COMBOBOX = "ComboBox"

# ---- 控件文本（按 Content/Name 匹配，依赖 DownKyi 当前语言）----
# DownKyi 1.6.1 默认中文界面
TEXT_BACK = "返回"
TEXT_DOWNLOAD_SELECTED = "下载选中项"  # 实测为"下载选中项"（不是"下载选中"）
TEXT_PARSE_VIDEO = "解析视频"          # 详情页底部右侧"解析视频"按钮
TEXT_PARSE_ALL = "全部解析"            # ViewParsingSelector 对话框"全部解析"按钮
TEXT_PARSE_CURRENT_SECTION = "解析当前分P"
TEXT_PARSE_SELECTED = "解析选中项"
TEXT_SET_PARSE_DEFAULT = "设为默认"
TEXT_DOWNLOAD = "下载"                  # ViewDownloadSetter 对话框"下载"按钮
TEXT_CANCEL = "取消"
TEXT_DOWNLOAD_ALL = "下载全部"
TEXT_SELECT_ALL = "全选"                # 详情页底部"全选" CheckBox
TEXT_OK = "确定"

# ---- 控件 ID 字典（统一引用）----
IDS = {
    "index_input": AUTO_ID_INDEX_INPUT,
    "detail_pages_list": AUTO_ID_DETAIL_PAGES,
    "detail_sections_list": AUTO_ID_DETAIL_SECTIONS,
    "btn_back": TEXT_BACK,
    "btn_parse_video": TEXT_PARSE_VIDEO,
    "btn_download_selected": TEXT_DOWNLOAD_SELECTED,
    "btn_download": TEXT_DOWNLOAD,
    "btn_cancel": TEXT_CANCEL,
    "chk_select_all": TEXT_SELECT_ALL,
    "chk_download_all": TEXT_DOWNLOAD_ALL,
    "btn_ok": TEXT_OK,
}

# ---- 日志 ----
LOG_FILE = "download_log.txt"
SCREENSHOT_DIR = "tests/screenshots"

# ---- 下载目录（仅用于参考/校验，脚本不依赖）----
# 可通过环境变量 BILI_DOWNLOAD_DIR 覆盖
import os

DEFAULT_DOWNLOAD_DIR = os.environ.get(
    "BILI_DOWNLOAD_DIR", r"C:\Users\Spark\Videos\Bili"
)
