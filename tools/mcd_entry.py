"""可选入口：把 CLI 版冻结成单文件可执行程序（默认构建流程已不再产出它）。

需要时在仓库根目录执行：

    pyinstaller --onefile --console --name MCD --icon packaging/icon.ico --paths . tools/mcd_entry.py

产出 dist/MCD.exe（Windows）或 dist/MCD（Linux/macOS）；日常直接用 `python -m mcd` 即可。
"""

from mcd.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
