"""Desktop UI package and stable historical localization imports."""

import sys

from shared import i18n_catalogs as _i18n_catalogs_module
from shared import localization as _localization_module

_PUBLIC_MODULE_ALIASES = {
    "i18n_catalogs": _i18n_catalogs_module,
    "localization": _localization_module,
}
for _module_name, _module in _PUBLIC_MODULE_ALIASES.items():
    sys.modules.setdefault(f"{__name__}.{_module_name}", _module)
    setattr(sys.modules[__name__], _module_name, _module)
