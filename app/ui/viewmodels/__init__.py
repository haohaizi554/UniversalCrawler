"""提供 GUI 页面使用的 view-model 工具。"""

import sys

from shared import failed_page_projection as _failed_page_projection_module
from shared import log_classification as _log_classification_module
from shared import log_detail_payloads as _log_detail_payloads_module
from shared import log_display as _log_display_module
from shared import log_i18n as _log_i18n_module
from shared import log_pipeline_rules as _log_pipeline_rules_module
from shared import settings_metadata as _settings_catalog_module

_PUBLIC_MODULE_ALIASES = {
    "failed_page_projection": _failed_page_projection_module,
    "log_classification": _log_classification_module,
    "log_detail_payloads": _log_detail_payloads_module,
    "log_display": _log_display_module,
    "log_i18n": _log_i18n_module,
    "log_pipeline_rules": _log_pipeline_rules_module,
    "settings_catalog": _settings_catalog_module,
}
for _module_name, _module in _PUBLIC_MODULE_ALIASES.items():
    sys.modules.setdefault(f"{__name__}.{_module_name}", _module)
    setattr(sys.modules[__name__], _module_name, _module)
