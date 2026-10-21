"""打包入口：把 mcdl 冻结成单文件可执行程序。

在仓库根目录执行：

    pyinstaller --onefile --console --name mcdl --paths . tools/mcdl_entry.py

产出 dist/mcdl.exe（Windows）或 dist/mcdl（Linux/macOS），双击或在命令行运行均可。
"""

from mcdl.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
