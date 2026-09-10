# ============================================================
# desktop/ui/ —— 桌面版界面
#
#   widgets.py           共用小控件（卡片 / 徽章 / 折叠区 / 文案清洗）
#   dialogs.py           新建分析、设置、模型管理
#   project_panel.py     📺 视频 / 项目信息
#   recommended_panel.py ⭐ 推荐剪辑
#   structure_panel.py   🧭 直播内容结构（Video → Chapter → Story）
#   developer_panel.py   🔧 开发者 / 调试
#   main_window.py       主窗口（左项目列表 + 右内容区）
# ============================================================

from .main_window import MainWindow

__all__ = ["MainWindow"]
