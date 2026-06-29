"""让 `python -m cli` 可用。"""

import sys
from cli.main import main

if __name__ == "__main__":
    sys.exit(main())
