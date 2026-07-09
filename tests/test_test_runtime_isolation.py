from __future__ import annotations

import os

from app.utils import runtime_paths


def test_pytest_default_user_data_root_is_isolated_from_workspace():
    root = runtime_paths.user_data_root()

    assert os.environ.get(runtime_paths.USER_DATA_ROOT_ENV)
    assert root != runtime_paths.project_root() / "user_data"
    assert root.name == "user_data"
