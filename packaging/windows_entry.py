"""PyInstaller 入口：使用绝对导入，避免以脚本方式运行包内 __main__ 时的相对导入问题。"""

import multiprocessing
import sys

from docmask.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
