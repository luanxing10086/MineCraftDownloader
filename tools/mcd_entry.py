"""打包入口：把 MCD 冻结成单文件可执行程序。

在仓库根目录执行：

    pyinstaller --onefile --console --name MCD --paths . tools/mcd_entry.py

产出 dist/MCD.exe（Windows）或 dist/mcd（Linux/macOS），双击或在命令行运行均可。
"""

from mcd.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
