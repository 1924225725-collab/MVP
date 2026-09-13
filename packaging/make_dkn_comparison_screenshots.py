"""生成 DKN HTML 路径基准与 QML 等价实现的逐帧对照图。

这是开发验收工具，不参与应用运行或发行打包。HTML 仅在临时目录中
隐藏最终黑场与副标题，以便独立比较路径、进度、辉光和笔尖。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_EDGE = Path(
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
)
TIMES = (0.45, 0.90, 1.20, 1.50)
WIDTH, HEIGHT = 1536, 1024


def _label(seconds: float) -> str:
    return f"{seconds:.2f}".replace(".", "_")


def capture_html(edge: Path, source: Path, output_dir: Path):
    html = source.read_text(encoding="utf-8")
    # Path-terminal reference: preserve the original script/path rendering and
    # suppress only lifecycle/content layers outside the comparison criteria.
    html = html.replace(
        "</style>",
        "#fade,#sub{display:none!important}\n</style>",
        1,
    )

    with tempfile.TemporaryDirectory(prefix="dkn-html-reference-") as temp:
        temp_dir = Path(temp)
        reference = temp_dir / "dkn_path_reference.html"
        reference.write_text(html, encoding="utf-8")
        profile = temp_dir / "edge-profile"

        for seconds in TIMES:
            target = output_dir / f"html_{_label(seconds)}s.png"
            url = f"{reference.as_uri()}?t={seconds:.2f}&hud=0"
            command = [
                str(edge),
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                "--force-device-scale-factor=1",
                f"--window-size={WIDTH},{HEIGHT}",
                f"--user-data-dir={profile}",
                f"--screenshot={target}",
                url,
            ]
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0 or not target.is_file():
                raise RuntimeError(
                    f"Edge HTML 截图失败（{seconds:.2f}s）："
                    f"{result.stderr.strip()}"
                )


def capture_qml(output_dir: Path):
    os.environ.setdefault("QT_QPA_PLATFORM", "windows")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")

    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from desktop.ui.brand_reveal import BrandReveal

    app = QApplication.instance() or QApplication([])
    reveal = BrandReveal()
    reveal.resize(WIDTH, HEIGHT)
    reveal.show()
    QTest.qWait(160)

    for seconds in TIMES:
        reveal.seek_reference(seconds)
        QTest.qWait(90)
        target = output_dir / f"qml_{_label(seconds)}s.png"
        image = reveal.grabFramebuffer()
        if image.isNull() or not image.save(str(target)):
            raise RuntimeError(f"QML 截图失败（{seconds:.2f}s）")

    reveal.close()
    app.processEvents()


def make_contact_sheet(output_dir: Path):
    from PIL import Image, ImageDraw

    thumb_w, thumb_h = 768, 512
    header = 42
    sheet = Image.new("RGB", (thumb_w * 2, (thumb_h + header) * 4), "#050506")
    draw = ImageDraw.Draw(sheet)

    for row, seconds in enumerate(TIMES):
        tag = _label(seconds)
        html = Image.open(output_dir / f"html_{tag}s.png").convert("RGB")
        qml = Image.open(output_dir / f"qml_{tag}s.png").convert("RGB")
        html.thumbnail((thumb_w, thumb_h))
        qml.thumbnail((thumb_w, thumb_h))
        y = row * (thumb_h + header)
        draw.text((18, y + 13), f"HTML PATH REFERENCE  {seconds:.2f}s", fill="#A6A8AD")
        draw.text((thumb_w + 18, y + 13), f"QML  {seconds:.2f}s", fill="#A6A8AD")
        sheet.paste(html, (0, y + header))
        sheet.paste(qml, (thumb_w, y + header))

    sheet.save(output_dir / "dkn_timeline_comparison.png")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--html",
        type=Path,
        required=True,
        help="原始 DKN HTML 视觉基准文件",
    )
    parser.add_argument("--edge", type=Path, default=DEFAULT_EDGE)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "outputs" / "ui_p0" / "dkn_comparison",
    )
    args = parser.parse_args()

    if not args.html.is_file():
        raise FileNotFoundError(f"HTML 视觉基准不存在：{args.html}")
    if not args.edge.is_file():
        raise FileNotFoundError(f"Microsoft Edge 不存在：{args.edge}")

    args.output.mkdir(parents=True, exist_ok=True)
    capture_html(args.edge, args.html, args.output)
    capture_qml(args.output)
    make_contact_sheet(args.output)
    print(args.output / "dkn_timeline_comparison.png")


if __name__ == "__main__":
    main()
