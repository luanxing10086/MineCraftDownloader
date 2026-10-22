"""允许 python -m mcd 直接运行。"""

from .cli import main

raise SystemExit(main())
