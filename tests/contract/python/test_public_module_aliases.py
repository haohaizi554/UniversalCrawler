from __future__ import annotations

import importlib
import subprocess
import sys

from app.services.media_library_runtime import MediaLibraryMixin
from app.ui.layout.top_bar import TopBarWidget
from shared.controller_session import ControllerSessionMixin
from shared.failed_page_projection import prepare_failed_item_for_display
from shared.frontend_page_definitions import PAGE_DEFINITIONS
from shared.i18n_catalogs import CATALOGS
from shared.localization import tr
from shared.log_classification import classification_facts
from shared.log_detail_payloads import soft_wrap_text
from shared.log_display import decorate_log_item
from shared.log_i18n import localize_log_text
from shared.log_pipeline_rules import is_download_boundary_log
from shared.settings_metadata import SETTING_DESCRIPTIONS


def test_historical_application_modules_resolve_to_canonical_objects() -> None:
    expected = {
        "app.controllers.session_mixin": ("ControllerSessionMixin", ControllerSessionMixin),
        "app.controllers.media_library_mixin": ("MediaLibraryMixin", MediaLibraryMixin),
        "app.services.frontend_page_definitions": ("PAGE_DEFINITIONS", PAGE_DEFINITIONS),
        "app.ui.components.top_bar": ("TopBarWidget", TopBarWidget),
        "app.ui.i18n_catalogs": ("CATALOGS", CATALOGS),
        "app.ui.localization": ("tr", tr),
        "app.ui.viewmodels.failed_page_projection": (
            "prepare_failed_item_for_display",
            prepare_failed_item_for_display,
        ),
        "app.ui.viewmodels.log_classification": ("classification_facts", classification_facts),
        "app.ui.viewmodels.log_detail_payloads": ("soft_wrap_text", soft_wrap_text),
        "app.ui.viewmodels.log_display": ("decorate_log_item", decorate_log_item),
        "app.ui.viewmodels.log_i18n": ("localize_log_text", localize_log_text),
        "app.ui.viewmodels.log_pipeline_rules": (
            "is_download_boundary_log",
            is_download_boundary_log,
        ),
        "app.ui.viewmodels.settings_catalog": ("SETTING_DESCRIPTIONS", SETTING_DESCRIPTIONS),
    }
    for module_name, (attribute, canonical) in expected.items():
        module = importlib.import_module(module_name)
        assert getattr(module, attribute) is canonical


def test_historical_application_module_imports_work_in_a_fresh_interpreter() -> None:
    probe = (
        "from app.controllers.session_mixin import ControllerSessionMixin; "
        "from app.services.frontend_page_definitions import PAGE_DEFINITIONS; "
        "from app.ui.localization import tr; "
        "from app.ui.viewmodels.log_i18n import localize_log_text; "
        "assert ControllerSessionMixin.__module__ == 'shared.controller_session'; "
        "assert PAGE_DEFINITIONS; "
        "assert tr.__module__ == 'shared.localization'; "
        "assert localize_log_text.__module__ == 'shared.log_i18n'"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
