# ============================================================
# desktop/workers.py —— 后台任务线程
#
# 【为什么需要】视频识别要跑几分钟、AI 分析要花几十秒到几分钟。
# 这些活必须在后台线程里跑，否则界面会假死（转圈都不转）。
#
# 用法：
#     w = TaskWorker(lambda progress: tasks.transcribe_video(path, progress))
#     w.progressChanged.connect(self.on_progress)
#     w.succeeded.connect(self.on_done)
#     w.failed.connect(self.on_error)      # 参数是原始异常
#     w.start()
#
# 线程里**只调 services 层**，不碰 Qt 控件；结果通过信号回主线程再更新界面。
# ============================================================

from PySide6.QtCore import QThread, Signal


class TaskWorker(QThread):
    """把一个耗时函数放到后台跑。

    fn(progress=...) -> 任意结果
      progress(str) 用来更新界面上的进度文字（跨线程发射信号是安全的）。
    """

    progressChanged = Signal(str)
    succeeded = Signal(object)
    failed = Signal(object)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn
        self._cancelled = False

    # ---- 取消 ----

    def cancel(self):
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    # ---- 线程体 ----

    def run(self):                                  # noqa: D102
        try:
            result = self._fn(progress=self.progressChanged.emit)
        except BaseException as e:                  # 兜住所有异常，绝不静默丢
            self.failed.emit(e)
            return
        self.succeeded.emit(result)
