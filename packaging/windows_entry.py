"""PyInstaller 桌面版入口：无控制台窗口，直接打开原生桌面窗口。"""

import multiprocessing
import sys

from docmask.desktop import _message_box, run_app

if __name__ == "__main__":
    multiprocessing.freeze_support()
    if len(sys.argv) > 1:
        _message_box(
            "命令行用法请使用压缩包里的 docmask-cli.exe。\n\n"
            "直接双击 docmask.exe 即可打开图形界面。"
        )
        sys.exit(2)
    try:
        code = run_app()
    except Exception as exc:
        _message_box(f"docmask 启动失败：{exc}")
        code = 1
    sys.exit(code)
