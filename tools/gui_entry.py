"""打包入口：图形界面版（PyInstaller --windowed）。

    pyinstaller --onefile --windowed --name mcd-gui --paths . tools/gui_entry.py
"""

from mcd.gui import main

if __name__ == "__main__":
    raise SystemExit(main())
