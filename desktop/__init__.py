# ============================================================
# desktop/ —— Windows 独立桌面版（V0.5）
#
# 目录职责：
#   desktop/services/  业务服务层（UI 只跟它打交道，不直接碰 analysis/pipeline/asr）
#   desktop/ui/        界面（PySide6 窗口、面板、对话框）
#   desktop/workers.py 后台线程（视频识别 / AI 分析都在后台跑，界面不卡）
#   desktop/theme.py   界面样式表
#
# 入口：项目根目录的 desktop_app.py
# ============================================================

APP_TITLE = "AI 直播切片助手"
APP_VERSION = "0.5.2"
