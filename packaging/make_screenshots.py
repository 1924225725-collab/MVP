# ============================================================
# packaging/make_screenshots.py —— 生成桌面版界面截图（用真实分析结果）
#
# 数据来源（**同一场 51 分钟视频**，不是编的）：
#   poc/v04_result.json         —— 真实 AI 分析产出（highlights / rejected / report / cost）
#   structures/测试视频2.json    —— 同一场视频的真实 Chapter / Story 结构缓存
#
# 做法：在**临时工作区**里组装一个项目，把四个页签各截一张图。
#       不动用户真实数据，也不联网、不调 AI。
#
# 用法：.\.venv\Scripts\python packaging\make_screenshots.py
# 产物：docs/screenshots/*.png
# ============================================================

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="lc_shot_"))
os.environ["LIVE_CLIPPER_HOME"] = str(TMP)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

OUT = ROOT / "docs" / "screenshots"


def build_demo_project():
    import app_paths
    app_paths.ensure_workspace()
    from analysis import story_context as sc
    from desktop.services import ProjectStore

    result = json.loads((ROOT / "poc" / "v04_result.json").read_text(encoding="utf-8"))
    raw = json.loads((ROOT / "structures" / "测试视频2.json").read_text(encoding="utf-8"))
    events = result.get("highlights") or []
    result["structure"] = sc.build_content_structure(sc.load_structure(raw), events)
    result["structure"]["source"] = "cache"
    result["structure_source"] = "cache"

    store = ProjectStore()
    proj = store.create("测试视频2.mp4", str(TMP / "videos" / "测试视频2.mp4"))
    store.save(ProjectStore.mark_transcribed(
        proj, TMP / "transcripts" / "测试视频2.txt", 1234))
    store.save(ProjectStore.mark_analyzed(
        proj, result, {"live_type": "娱乐聊天", "token_mode": "精细",
                       "quantity_mode": "自动精选", "custom_count": 10}))
    return proj


def main():
    proj = build_demo_project()

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from desktop import theme
    from desktop.ui import MainWindow

    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(theme.QSS)

    win = MainWindow()
    win.resize(1420, 940)
    win.show()
    win.load_project(proj["project_id"])
    app.processEvents()

    OUT.mkdir(parents=True, exist_ok=True)
    saved = []

    def shot(name: str, widget=None, min_height=None):
        w = widget or win
        if min_height:
            w.setMinimumHeight(min_height)
            app.processEvents()
        pm = w.grab()
        path = OUT / name
        pm.save(str(path))
        saved.append((path, pm.width(), pm.height()))
        print(f"  ✔ {path.name}  {pm.width()}x{pm.height()}")

    # 1) 总览：推荐剪辑页
    win.tabs.setCurrentWidget(win.panel_recommended)
    app.processEvents()
    shot("01_推荐剪辑.png", win)

    # 2) 推荐剪辑完整长图（切到「全部候选」，一张图看全 13 条）
    win.panel_recommended.filter_box.setCurrentText("全部候选")
    app.processEvents()
    inner = win.panel_recommended.inner
    shot("02_推荐剪辑_全部卡片.png", inner, min_height=inner.sizeHint().height())
    inner.setMinimumHeight(0)
    win.panel_recommended.filter_box.setCurrentText("只看推荐")
    app.processEvents()

    # 3) 内容结构（Chapter → Story）：默认折叠，这里展开前两个看 Story 层
    win.tabs.setCurrentWidget(win.panel_structure)
    app.processEvents()
    shot("03_直播内容结构.png", win)
    from desktop.ui.widgets import Collapsible
    cols = win.panel_structure.findChildren(Collapsible)
    for c in cols[:2]:
        c._btn.setChecked(True)
    app.processEvents()
    inner2 = win.panel_structure.inner
    shot("04_内容结构_展开长图.png", inner2, min_height=inner2.sizeHint().height())
    inner2.setMinimumHeight(0)

    # 4) 视频信息
    win.tabs.setCurrentWidget(win.panel_project)
    app.processEvents()
    shot("05_视频信息.png", win)

    # 5) 开发者视图
    win.tabs.setCurrentWidget(win.panel_developer)
    app.processEvents()
    shot("06_开发者视图.png", win)

    win.close()
    print(f"\n截图共 {len(saved)} 张 → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
