"""允许 python -m mcdl 直接运行。"""

from .cli import main

raise SystemExit(main())
