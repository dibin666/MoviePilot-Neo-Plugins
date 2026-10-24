"""插件单测引导：复用 MoviePilot NEO 后端的共享测试 harness。

运行前通过环境变量 ``MOVIEPILOT_BACKEND`` 指向 moviepilot-neo 后端检出目录，例如::

    MOVIEPILOT_BACKEND=/path/to/moviepilot-neo pytest tests
"""
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = os.environ.get("MOVIEPILOT_BACKEND")

if not BACKEND or not (Path(BACKEND) / "app").is_dir():
    raise pytest.UsageError("请设置 MOVIEPILOT_BACKEND 为 moviepilot-neo 后端目录")

sys.path.insert(0, str(Path(BACKEND).resolve()))

from app.testing.bootstrap import prepare_v2_backend  # noqa: E402

prepare_v2_backend(REPO_ROOT)

from app.testing.network_guard import block_real_network  # noqa: E402,F401
