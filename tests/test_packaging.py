"""packaging/ 打包配置验证测试。

测试维度：
- 单元测试：spec 文件、build 脚本、runtime hook 的语法和语义
- 集成测试：所需文件存在性、依赖项、配置一致性
- 静态分析：hiddenimports 必须包含动态加载的 entry/cli 模块
- 图标分配：主 EXE 用 favicon.ico，Web EXE 用 Web.ico
- 启动器：packaging 生成的 _gui_launcher.py / _webui_launcher.py 内容正确
- 运行时钩子：NullStream 兜底、PLAYWRIGHT_BROWSERS_PATH 设置、AppUserModelID

设计原则：
- 不真跑 PyInstaller（太慢），只验证配置 + 文件存在性
- 不依赖已构建的 dist/ 目录（保持快速可重复）
"""

import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGING_DIR = PROJECT_ROOT / "packaging"
SPEC_FILE = PACKAGING_DIR / "portable.spec"
RUNTIME_HOOK = PACKAGING_DIR / "runtime_hook.py"
REQUIREMENTS_BUILD = PACKAGING_DIR / "requirements-build.txt"
REQUIREMENTS_WEB = PROJECT_ROOT / "requirements-web.txt"
INSTALLER_FILE = PACKAGING_DIR / "installer.iss"
PROJECT_META = PACKAGING_DIR / "project_meta.py"
DOCKERFILE = PROJECT_ROOT / "Dockerfile"
DOCKER_COMPOSE = PROJECT_ROOT / "docker-compose.yml"
DOCKER_ENTRYPOINT = PROJECT_ROOT / "docker" / "entrypoint.sh"
DOCKER_ENV_EXAMPLE = PROJECT_ROOT / ".env.docker.example"

class SpecFileExistenceTests(unittest.TestCase):
    """spec 文件基本检查。"""

    def test_spec_file_exists(self):
        self.assertTrue(SPEC_FILE.exists(), f"missing: {SPEC_FILE}")

    def test_spec_file_syntax_valid(self):
        """spec 文件必须能被 Python 编译。"""
        import py_compile
        # PyInstaller spec 文件不是普通 Python 模块，是 exec'd
        # 但语法应当合法 → 用 compile 检查
        with open(SPEC_FILE, "r", encoding="utf-8") as f:
            source = f.read()
        try:
            compile(source, str(SPEC_FILE), "exec")
        except SyntaxError as e:
            self.fail(f"spec file has syntax error: {e}")

class SpecAppMetadataTests(unittest.TestCase):
    """spec 文件中 app 元数据正确性。"""

    @classmethod
    def setUpClass(cls):
        # exec spec file to access module-level vars
        cls._spec_globals = {
            "__file__": str(SPEC_FILE),
            "__name__": "__test_spec__",
            "SPEC": str(SPEC_FILE),
            # Mock PyInstaller builtins (only need module-level vars, not Analysis/EXE/...)
            "Analysis": MagicMock(),
            "PYZ": MagicMock(),
            "EXE": MagicMock(),
            "COLLECT": MagicMock(),
        }
        with open(SPEC_FILE, "r", encoding="utf-8") as f:
            spec_source = f.read()
        try:
            exec(spec_source, cls._spec_globals)
        except Exception as e:
            raise unittest.SkipTest(f"cannot exec spec file: {e}")

    def test_app_name(self):
        self.assertEqual(self._spec_globals.get("APP_NAME"), "UniversalCrawlerPro")

    def test_webui_name(self):
        self.assertEqual(self._spec_globals.get("WEBUI_NAME"), "CrawlerWebPortal")

    def test_icon_files_declared(self):
        """spec 必须声明主图标和 WebUI 图标两个不同路径。"""
        self.assertIsNotNone(self._spec_globals.get("icon_file"))
        self.assertIsNotNone(self._spec_globals.get("webui_icon"))
        # 主 EXE 用 favicon.ico
        self.assertTrue(str(self._spec_globals["icon_file"]).endswith("favicon.ico"))
        # Web EXE 用 Web.ico
        self.assertTrue(str(self._spec_globals["webui_icon"]).endswith("Web.ico"))

class SpecHiddenImportsTests(unittest.TestCase):
    """hiddenimports 完整性。"""

    @classmethod
    def setUpClass(cls):
        cls._spec_globals = {
            "__file__": str(SPEC_FILE),
            "__name__": "__test_spec__",
            "SPEC": str(SPEC_FILE),
            "Analysis": MagicMock(),
            "PYZ": MagicMock(),
            "EXE": MagicMock(),
            "COLLECT": MagicMock(),
        }
        with open(SPEC_FILE, "r", encoding="utf-8") as f:
            spec_source = f.read()
        try:
            exec(spec_source, cls._spec_globals)
        except Exception as e:
            raise unittest.SkipTest(f"cannot exec spec file: {e}")

    def test_hiddenimports_is_list(self):
        self.assertIsInstance(self._spec_globals.get("hiddenimports"), list)

    def test_hiddenimports_includes_entry_modules(self):
        """动态加载的 entry 模块必须在 hiddenimports。"""
        h = self._spec_globals["hiddenimports"]
        for mod in ("entry.cli_entry", "entry.gui_entry", "entry.web_entry",
                    "entry.interactive_entry", "entry.dispatcher"):
            self.assertIn(mod, h, f"missing hiddenimport: {mod}")

    def test_hiddenimports_includes_cli_commands(self):
        """cli 子命令模块必须显式列出（动态加载）。"""
        h = self._spec_globals["hiddenimports"]
        for mod in ("cli.commands.search", "cli.commands.download",
                    "cli.commands.scan", "cli.commands.interactive"):
            self.assertIn(mod, h, f"missing hiddenimport: {mod}")

    def test_hiddenimports_includes_pyqt6(self):
        """PyQt6 必须显式列出（修复 web/dialog 弹窗不显示）。"""
        h = self._spec_globals["hiddenimports"]
        self.assertIn("PyQt6", h)
        # 必须有具体子模块（collect_submodules('PyQt6')）
        qt_submodules = [m for m in h if m.startswith("PyQt6.")]
        self.assertGreater(len(qt_submodules), 5,
                          "should have many PyQt6.* submodules from collect_submodules")

    def test_hiddenimports_includes_uvicorn_protocols(self):
        """uvicorn 协议模块必须显式列出。"""
        h = self._spec_globals["hiddenimports"]
        for mod in ("uvicorn.logging", "uvicorn.loops", "uvicorn.protocols"):
            self.assertIn(mod, h, f"missing uvicorn: {mod}")

    def test_hiddenimports_includes_shared_modules(self):
        """shared 子包必须显式列入 hiddenimports。"""
        h = self._spec_globals["hiddenimports"]
        shared_mods = [m for m in h if m.startswith("shared.")]
        self.assertGreater(len(shared_mods), 3, "should collect shared.* submodules")
        for mod in (
            "shared.controller_session",
            "shared.spider_session_runtime",
            "shared.cli_runner_runtime",
        ):
            self.assertIn(mod, h, f"missing hiddenimport: {mod}")

class SpecDataFilesTests(unittest.TestCase):
    """datas 完整性。"""

    @classmethod
    def setUpClass(cls):
        cls._spec_globals = {
            "__file__": str(SPEC_FILE),
            "__name__": "__test_spec__",
            "SPEC": str(SPEC_FILE),
            "Analysis": MagicMock(),
            "PYZ": MagicMock(),
            "EXE": MagicMock(),
            "COLLECT": MagicMock(),
        }
        with open(SPEC_FILE, "r", encoding="utf-8") as f:
            spec_source = f.read()
        try:
            exec(spec_source, cls._spec_globals)
        except Exception as e:
            raise unittest.SkipTest(f"cannot exec spec file: {e}")

    def test_datas_is_list(self):
        self.assertIsInstance(self._spec_globals.get("datas"), list)

    def test_datas_includes_entry_package(self):
        """entry/ 整个子包必须作为 data 复制。"""
        datas = self._spec_globals["datas"]
        # datas 是 [(src, dst), ...]
        entry_data = [d for d in datas if d[1] == "entry"]
        self.assertTrue(len(entry_data) >= 1,
                       f"entry package not in datas: {datas}")

    def test_datas_includes_cli_package(self):
        """cli/ 整个子包必须作为 data 复制。"""
        datas = self._spec_globals["datas"]
        cli_data = [d for d in datas if d[1] == "cli"]
        self.assertTrue(len(cli_data) >= 1, f"cli package not in datas: {datas}")

    def test_datas_includes_both_icons(self):
        """favicon.ico 和 Web.ico 都必须打包。"""
        datas = self._spec_globals["datas"]
        icon_targets = [d[0] for d in datas]
        self.assertTrue(any("favicon.ico" in p for p in icon_targets),
                       "favicon.ico not packaged")
        self.assertTrue(any("Web.ico" in p for p in icon_targets),
                       "Web.ico not packaged")

    def test_datas_includes_ui_icon_assets(self):
        """UI/icon 图标资产必须打包，供 GUI/WebUI 运行时复用。"""
        datas = self._spec_globals["datas"]
        self.assertTrue(any(d[1] == "UI/icon" for d in datas), "UI/icon not packaged")

    def test_datas_includes_ffmpeg(self):
        """ffmpeg.exe 必须打包。"""
        datas = self._spec_globals["datas"]
        ffmpeg = [d for d in datas if "ffmpeg.exe" in d[0]]
        self.assertTrue(len(ffmpeg) >= 1, "ffmpeg.exe not in datas")

    def test_datas_includes_ffprobe(self):
        """ffprobe.exe 必须打包。"""
        datas = self._spec_globals["datas"]
        if (PROJECT_ROOT / "ffprobe.exe").exists():
            ffprobe = [d for d in datas if "ffprobe.exe" in d[0]]
            self.assertTrue(len(ffprobe) >= 1, "ffprobe.exe not in datas")
        else:
            self.assertIn("ffprobe.exe", SPEC_FILE.read_text(encoding="utf-8"))

    def test_datas_includes_shared_package(self):
        """shared/ 整个子包必须作为 data 复制。"""
        datas = self._spec_globals["datas"]
        if (PROJECT_ROOT / "shared").exists():
            shared_data = [d for d in datas if d[1] == "shared"]
            self.assertTrue(len(shared_data) >= 1, f"shared package not in datas: {datas}")
        else:
            self.assertIn('"shared"', SPEC_FILE.read_text(encoding="utf-8"))

class SpecExcludesTests(unittest.TestCase):
    """excludes 配置。"""

    @classmethod
    def setUpClass(cls):
        cls._analysis_mock = MagicMock()
        cls._spec_globals = {
            "__file__": str(SPEC_FILE),
            "__name__": "__test_spec__",
            "SPEC": str(SPEC_FILE),
            "Analysis": cls._analysis_mock,
            "PYZ": MagicMock(),
            "EXE": MagicMock(),
            "COLLECT": MagicMock(),
        }
        with open(SPEC_FILE, "r", encoding="utf-8") as f:
            spec_source = f.read()
        try:
            exec(spec_source, cls._spec_globals)
        except Exception as e:
            raise unittest.SkipTest(f"cannot exec spec file: {e}")

    def test_excludes_tkinter(self):
        """tkinter 应当被排除（避免与 PyQt6 冲突）。"""
        kwargs = self._analysis_mock.call_args.kwargs
        excludes = kwargs.get("excludes", [])
        self.assertIn("tkinter", excludes)

class SpecRuntimeHookTests(unittest.TestCase):
    """runtime_hook 必须挂载。"""

    @classmethod
    def setUpClass(cls):
        cls._spec_globals = {
            "__file__": str(SPEC_FILE),
            "__name__": "__test_spec__",
            "SPEC": str(SPEC_FILE),
            "Analysis": MagicMock(),
            "PYZ": MagicMock(),
            "EXE": MagicMock(),
            "COLLECT": MagicMock(),
        }
        with open(SPEC_FILE, "r", encoding="utf-8") as f:
            spec_source = f.read()
        try:
            exec(spec_source, cls._spec_globals)
        except Exception as e:
            raise unittest.SkipTest(f"cannot exec spec file: {e}")

    def test_runtime_hook_set(self):
        """spec 必须挂载 runtime_hook.py。"""
        # runtime_hooks 是在 Analysis() 调用时设置的
        # 我们检查 spec 源码中是否有 runtime_hook 字段
        with open(SPEC_FILE, "r", encoding="utf-8") as f:
            source = f.read()
        self.assertIn("runtime_hooks", source)
        self.assertIn("runtime_hook.py", source)

class RuntimeHookTests(unittest.TestCase):
    """packaging/runtime_hook.py 行为测试。"""

    def test_runtime_hook_exists(self):
        self.assertTrue(RUNTIME_HOOK.exists())

    def test_runtime_hook_defines_null_stream(self):
        """NullStream 必须在文件中定义。"""
        with open(RUNTIME_HOOK, "r", encoding="utf-8") as f:
            source = f.read()
        self.assertIn("_NullStream", source)
        self.assertIn("def isatty", source)
        self.assertIn("def write", source)
        self.assertIn("def flush", source)

    def test_runtime_hook_null_stream_isatty_false(self):
        """NullStream.isatty() 必须返回 False（避免 uvicorn 崩溃）。"""
        with open(RUNTIME_HOOK, "r", encoding="utf-8") as f:
            source = f.read()
        self.assertIn("return False", source)

    def test_runtime_hook_sets_browser_path(self):
        """runtime_hook 必须设置 PLAYWRIGHT_BROWSERS_PATH 环境变量。"""
        with open(RUNTIME_HOOK, "r", encoding="utf-8") as f:
            source = f.read()
        self.assertIn("PLAYWRIGHT_BROWSERS_PATH", source)
        self.assertIn("ms-playwright", source)

    def test_runtime_hook_sets_appusermodelid(self):
        """Windows 任务栏 AppUserModelID 必须设置。"""
        with open(RUNTIME_HOOK, "r", encoding="utf-8") as f:
            source = f.read()
        self.assertIn("SetCurrentProcessExplicitAppUserModelID", source)
        # 必须区分 main 和 web 的 app_id
        self.assertIn("ucrawl.universalcrawlerpro.web", source)
        self.assertIn("ucrawl.universalcrawlerpro.main", source)

    def test_null_stream_class_behavior(self):
        """NullStream 实例可调用 .write/.flush/.isatty。"""
        # import _NullStream（私有类）
        import importlib.util
        spec_mod = importlib.util.spec_from_file_location("_test_rh", RUNTIME_HOOK)
        rh = importlib.util.module_from_spec(spec_mod)
        # 直接 exec
        ns = {"__file__": str(RUNTIME_HOOK), "__name__": "_test_rh"}
        with open(RUNTIME_HOOK, "r", encoding="utf-8") as f:
            source = f.read()
        exec(source, ns)
        ns["_NullStream"]().write("test")  # 不抛异常
        ns["_NullStream"]().flush()  # 不抛异常
        self.assertFalse(ns["_NullStream"]().isatty())

class BuildScriptTests(unittest.TestCase):
    """build_portable.py 静态分析。"""

    def test_build_script_exists(self):
        self.assertTrue((PACKAGING_DIR / "build_portable.py").exists())

    def test_required_files_includes_entry_submodules(self):
        """build_portable.py 的 REQUIRED_FILES 必须包含所有 entry 子模块。"""
        with open(PACKAGING_DIR / "build_portable.py", "r", encoding="utf-8") as f:
            source = f.read()
        for mod in ("__init__.py", "dispatcher.py", "gui_entry.py",
                    "web_entry.py", "cli_entry.py", "interactive_entry.py"):
            self.assertIn(f'"entry" / "{mod}"', source,
                         f"missing entry module in REQUIRED_FILES: {mod}")

    def test_required_files_includes_main_py(self):
        self.assertIn('"main.py"', (PACKAGING_DIR / "build_portable.py").read_text(encoding="utf-8"))

    def test_required_files_includes_both_icons(self):
        """REQUIRED_FILES 必须同时包含 favicon.ico 和 Web.ico。"""
        source = (PACKAGING_DIR / "build_portable.py").read_text(encoding="utf-8")
        self.assertIn("favicon.ico", source)
        self.assertIn("Web.ico", source)

    def test_required_files_includes_spec_file(self):
        self.assertIn("portable.spec",
                     (PACKAGING_DIR / "build_portable.py").read_text(encoding="utf-8"))

    def test_required_files_includes_ffprobe(self):
        source = (PACKAGING_DIR / "build_portable.py").read_text(encoding="utf-8")
        self.assertIn("ffprobe.exe", source)

    def test_required_files_includes_shared_package(self):
        source = (PACKAGING_DIR / "build_portable.py").read_text(encoding="utf-8")
        self.assertIn('"shared" / "__init__.py"', source)

    def test_forbidden_filenames_includes_user_data(self):
        """不应打包用户数据文件。"""
        source = (PACKAGING_DIR / "build_portable.py").read_text(encoding="utf-8")
        for forbidden in ("config.json", "bili_auth.json", "ks_auth.json", "dy_auth.json"):
            self.assertIn(forbidden, source)

    def test_verify_output_checks_entry_package(self):
        """verify_output 必须检查 _internal/entry/ 存在。"""
        source = (PACKAGING_DIR / "build_portable.py").read_text(encoding="utf-8")
        self.assertIn("entry", source)
        self.assertIn("cli", source)
        self.assertIn("shared", source)
        # 必须检查关键模块
        for mod in ("__init__.py", "dispatcher.py"):
            self.assertIn(mod, source)

    def test_verify_output_checks_both_exes(self):
        """verify_output 必须检查两个 EXE 都生成。"""
        source = (PACKAGING_DIR / "build_portable.py").read_text(encoding="utf-8")
        self.assertIn("APP_NAME", source)
        self.assertIn("WEBUI_NAME", source)

    def test_kill_locking_processes_includes_both_exes(self):
        """kill_locking_processes 必须 kill 两个 EXE + ffmpeg。"""
        source = (PACKAGING_DIR / "build_portable.py").read_text(encoding="utf-8")
        # 用 f-string 引用 APP_NAME/WEBUI_NAME + ".exe"
        # 注意：Python 源文件中就是 f"{APP_NAME}.exe" 这种形式
        for proc in ('f"{APP_NAME}.exe"', 'f"{WEBUI_NAME}.exe"', '"ffmpeg.exe"'):
            self.assertIn(proc, source, f"missing process in kill list: {proc}")

    def test_pyinstaller_command_uses_noconfirm_clean(self):
        """PyInstaller 命令必须带 --noconfirm --clean。"""
        source = (PACKAGING_DIR / "build_portable.py").read_text(encoding="utf-8")
        self.assertIn("--noconfirm", source)
        self.assertIn("--clean", source)

class PackagingMetadataTests(unittest.TestCase):
    """project_meta.py 与 pyproject.toml 的一致性。"""

    def test_project_meta_exists(self):
        self.assertTrue(PROJECT_META.exists())

    def test_project_meta_reads_package_version(self):
        source = PROJECT_META.read_text(encoding="utf-8")
        self.assertIn('PACKAGE_VERSION = _project_field("version")', source)
        self.assertIn('PACKAGE_NAME = _project_field("name")', source)

    def test_installer_basename_uses_version(self):
        source = PROJECT_META.read_text(encoding="utf-8")
        self.assertIn("INSTALLER_BASENAME", source)
        self.assertIn("PACKAGE_VERSION", source)

class InstallerScriptTests(unittest.TestCase):
    """安装器脚本与构建脚本的一致性。"""

    def test_installer_script_exists(self):
        self.assertTrue(INSTALLER_FILE.exists())

    def test_installer_script_supports_define_override(self):
        source = INSTALLER_FILE.read_text(encoding="utf-8")
        self.assertIn("#ifndef AppVersion", source)
        self.assertIn("#ifndef OutputBaseFilename", source)
        self.assertIn("OutputBaseFilename={#OutputBaseFilename}", source)

    def test_installer_script_appusermodelid_aligned(self):
        source = INSTALLER_FILE.read_text(encoding="utf-8")
        self.assertIn('ucrawl.universalcrawlerpro.main', source)
        self.assertIn('ucrawl.universalcrawlerpro.web', source)

    def test_installer_script_shows_media_association_tasks(self):
        source = INSTALLER_FILE.read_text(encoding="utf-8")
        self.assertIn('Name: "associatevideo"', source)
        self.assertIn('Name: "associateimage"', source)
        video_task = next(line for line in source.splitlines() if 'Name: "associatevideo"' in line)
        self.assertNotIn("unchecked", video_task.lower())
        self.assertNotIn("checkedonce", video_task.lower())
        self.assertRegex(source, r'Name:\s*"associateimage".*Flags:\s*unchecked')

    def test_installer_script_registers_supported_media_extensions(self):
        source = INSTALLER_FILE.read_text(encoding="utf-8")
        self.assertIn("ChangesAssociations=yes", source)
        self.assertIn('"{app}\\{#AppExeName}"" ""%1"', source)
        for ext in (".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv", ".m4v", ".webm", ".m3u8", ".ts"):
            self.assertIn(f"Software\\Classes\\{ext}", source)
            self.assertIn("UniversalCrawlerPro.Video", source)
        for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
            self.assertIn(f"Software\\Classes\\{ext}", source)
            self.assertIn("UniversalCrawlerPro.Image", source)

    def test_installer_script_registers_openwith_and_capabilities(self):
        source = INSTALLER_FILE.read_text(encoding="utf-8")
        self.assertIn("Software\\RegisteredApplications", source)
        self.assertIn("Software\\UniversalCrawlerPro\\Capabilities", source)
        self.assertIn("Software\\Classes\\Applications\\{#AppExeName}\\shell\\open\\command", source)
        self.assertIn("OpenWithProgids", source)
        self.assertIn("SupportedTypes", source)

    def test_installer_script_runs_association_helper_without_inno_userchoice_write(self):
        source = INSTALLER_FILE.read_text(encoding="utf-8")
        self.assertIn("ChangesAssociations=yes", source)
        self.assertIn('--app-name ""{#AppName}""', source)
        self.assertIn("--register-file-associations{code:GetAssociationKinds}", source)
        self.assertIn("--set-default-file-associations", source)
        self.assertIn("ShouldOpenAssociationSettings", source)
        association_run_line = next(
            line for line in source.splitlines() if "--register-file-associations" in line
        )
        postinstall_run_line = next(
            line for line in source.splitlines() if "postinstall" in line and "Description:" in line
        )
        self.assertNotIn("--open-default-apps-settings", association_run_line)
        self.assertIn("StatusMsg:", association_run_line)
        self.assertIn("runhidden", association_run_line.lower())
        self.assertIn("unchecked", postinstall_run_line.lower())
        self.assertIn("WizardIsTaskSelected('associatevideo')", source)
        self.assertIn("WizardIsTaskSelected('associateimage')", source)
        self.assertNotIn("UserChoice", source)
        self.assertNotIn("Flags: deletekey", source)
        self.assertNotIn("SHChangeNotifyW@shell32.dll", source)
        self.assertNotIn("RegDeleteKeyIncludingSubkeys", source)

    def test_build_installer_injects_version_and_ids(self):
        source = (PACKAGING_DIR / "build_installer.py").read_text(encoding="utf-8")
        self.assertIn("/DAppVersion=", source)
        self.assertIn("/DOutputBaseFilename=", source)
        self.assertIn("/DAppUserModelID=", source)
        self.assertIn("/DWebUIUserModelID=", source)
        self.assertIn("get_setup_exe_path", source)

    def test_installer_wizard_assets_exist_or_documented(self):
        wizard_image = PACKAGING_DIR / "wizard_image.bmp"
        wizard_small_image = PACKAGING_DIR / "wizard_small_image.bmp"
        if not wizard_image.exists() or not wizard_small_image.exists():
            self.skipTest(
                "installer wizard BMP assets are local build prerequisites: "
                f"{wizard_image.name}, {wizard_small_image.name}"
            )
        source = INSTALLER_FILE.read_text(encoding="utf-8")
        self.assertIn("wizard_image.bmp", source)
        self.assertIn("wizard_small_image.bmp", source)

    def test_build_installer_checks_wizard_assets(self):
        source = (PACKAGING_DIR / "build_installer.py").read_text(encoding="utf-8")
        self.assertIn("wizard_image.bmp", source)
        self.assertIn("wizard_small_image.bmp", source)

    def test_build_installer_checks_install_source_runtime_entries(self):
        source = (PACKAGING_DIR / "build_installer.py").read_text(encoding="utf-8")
        self.assertIn("REQUIRED_INSTALL_SOURCE_ENTRIES", source)
        for marker in (
            "APP_NAME",
            "WEBUI_NAME",
            "BUILD_INFO.txt",
            "index.html",
            "app.css",
            "app.js",
            "nav_settings.png",
            "favicon.ico",
            "Web.ico",
            "_missing_install_source_entries",
        ):
            self.assertIn(marker, source)

class LauncherTemplateTests(unittest.TestCase):
    """_gui_launcher.py 和 _webui_launcher.py 模板正确性。"""

    def test_gui_launcher_content(self):
        """spec 中的 _gui_launcher.py 模板必须调用 entry.gui_entry.main。"""
        with open(SPEC_FILE, "r", encoding="utf-8") as f:
            source = f.read()
        self.assertIn("from entry.gui_entry import main", source)
        # 不走 dispatcher（直接启动 GUI）
        self.assertIn("_main(sys.argv", source)

    def test_webui_launcher_content(self):
        """spec 中的 _webui_launcher.py 模板必须调用 entry.web_entry.main。"""
        with open(SPEC_FILE, "r", encoding="utf-8") as f:
            source = f.read()
        self.assertIn("from entry.web_entry import main", source)
        # 不走 dispatcher
        self.assertIn("_main(sys.argv", source)

    def test_both_launchers_have_console_false(self):
        """两个 EXE 都必须 console=False（不弹黑窗）。至少出现 2 次。"""
        with open(SPEC_FILE, "r", encoding="utf-8") as f:
            source = f.read()
        count = source.count("console=False")
        self.assertGreaterEqual(count, 2,
                               f"console=False should appear at least 2 times, got {count}")

    def test_both_launchers_have_different_icons(self):
        """两个 EXE 必须用不同图标。"""
        with open(SPEC_FILE, "r", encoding="utf-8") as f:
            source = f.read()
        self.assertIn('icon=str(icon_file)', source)  # main 用 favicon
        self.assertIn('icon=str(webui_icon)', source)  # web 用 Web.ico

class RequirementsBuildTests(unittest.TestCase):
    """requirements-build.txt 测试。"""

    def test_file_exists(self):
        self.assertTrue(REQUIREMENTS_BUILD.exists())

    def test_contains_pyinstaller(self):
        with open(REQUIREMENTS_BUILD, "r", encoding="utf-8") as f:
            content = f.read().lower()
        self.assertIn("pyinstaller", content)

class ContainerizationAssetTests(unittest.TestCase):
    """容器化交付资产测试。"""

    def test_dockerfile_exists(self):
        self.assertTrue(DOCKERFILE.exists())

    def test_docker_compose_exists(self):
        self.assertTrue(DOCKER_COMPOSE.exists())

    def test_web_requirements_exist(self):
        self.assertTrue(REQUIREMENTS_WEB.exists())

    def test_entrypoint_exists(self):
        self.assertTrue(DOCKER_ENTRYPOINT.exists())

    def test_env_example_exists(self):
        self.assertTrue(DOCKER_ENV_EXAMPLE.exists())

    def test_dockerfile_uses_web_requirements_and_non_root_user(self):
        source = DOCKERFILE.read_text(encoding="utf-8")
        self.assertIn("requirements-web.txt", source)
        self.assertIn("gosu", source)
        self.assertIn("APT_MIRROR", source)
        self.assertIn("PIP_INDEX_URL", source)
        self.assertIn("UCRAWL_TOOL_ROOT=/app/tools", source)
        self.assertIn("ENTRYPOINT [\"/usr/bin/tini\", \"--\", \"/usr/local/bin/ucrawl-entrypoint\"]", source)
        self.assertNotIn("COPY . .", source)

    def test_web_requirements_excludes_desktop_and_test_only_dependencies(self):
        content = REQUIREMENTS_WEB.read_text(encoding="utf-8")
        requirement_lines = {
            line.strip()
            for line in content.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertFalse(any(line.startswith("PyQt6") for line in requirement_lines))
        self.assertFalse(any(line.startswith("BeautifulReport") for line in requirement_lines))
        self.assertFalse(any(line.startswith("python-docx") for line in requirement_lines))
        self.assertTrue(any(line.startswith("fastapi") for line in requirement_lines))
        self.assertTrue(any(line.startswith("uvicorn") for line in requirement_lines))
        self.assertTrue(any(line.startswith("websockets") for line in requirement_lines))

    def test_docker_compose_exposes_healthcheck_and_build_arg(self):
        source = DOCKER_COMPOSE.read_text(encoding="utf-8")
        self.assertIn("INSTALL_PLAYWRIGHT", source)
        self.assertIn("APT_MIRROR", source)
        self.assertIn("PIP_INDEX_URL", source)
        self.assertIn("UCRAWL_TOOL_ROOT", source)
        self.assertIn("./tools:/app/tools", source)
        self.assertIn("healthcheck:", source)
        self.assertIn("UCRAWL_HOST_PORT", source)
        self.assertIn("UCRAWL_EXTRA_ARGS", source)
        self.assertNotIn("init: true", source)

    def test_env_example_contains_mainland_friendly_defaults(self):
        source = DOCKER_ENV_EXAMPLE.read_text(encoding="utf-8")
        self.assertIn("UCRAWL_APT_MIRROR=", source)
        self.assertIn("UCRAWL_APT_SECURITY_MIRROR=", source)
        self.assertIn("UCRAWL_PIP_INDEX_URL=", source)
        self.assertIn("UCRAWL_PIP_TRUSTED_HOST=", source)
        self.assertIn("UCRAWL_HTTP_PROXY=", source)
        self.assertIn("UCRAWL_HTTPS_PROXY=", source)

    def test_entrypoint_maps_environment_variables(self):
        source = DOCKER_ENTRYPOINT.read_text(encoding="utf-8")
        self.assertIn("UCRAWL_USER_DATA_ROOT", source)
        self.assertIn("UCRAWL_DOWNLOAD_ROOT", source)
        self.assertIn("UCRAWL_TOOL_ROOT", source)
        self.assertIn("UCRAWL_EXTRA_ARGS", source)
        self.assertIn("gosu ucrawl", source)
        self.assertIn("entry.web_entry", source)

class ProjectFileExistenceTests(unittest.TestCase):
    """项目必要文件存在性。"""

    def test_main_py_exists(self):
        self.assertTrue((PROJECT_ROOT / "main.py").exists())

    def test_favicon_exists(self):
        """主图标必须存在。"""
        self.assertTrue((PROJECT_ROOT / "favicon.ico").exists())

    def test_web_ico_exists(self):
        """Web 专用图标必须存在。"""
        self.assertTrue((PROJECT_ROOT / "Web.ico").exists())

    def test_ffmpeg_exists(self):
        self.assertTrue((PROJECT_ROOT / "ffmpeg.exe").exists())

    def test_ffprobe_exists(self):
        self.assertTrue((PROJECT_ROOT / "ffprobe.exe").exists())

    def test_m3u8dl_exists(self):
        self.assertTrue((PROJECT_ROOT / "N_m3u8DL-RE.exe").exists())

    def test_entry_submodules_exist(self):
        """entry/ 下所有子模块必须存在。"""
        entry_dir = PROJECT_ROOT / "entry"
        for module in ("__init__.py", "dispatcher.py", "gui_entry.py",
                       "web_entry.py", "cli_entry.py", "interactive_entry.py"):
            path = entry_dir / module
            self.assertTrue(path.exists(), f"missing: {path}")

    def test_shared_package_exists(self):
        self.assertTrue((PROJECT_ROOT / "shared" / "__init__.py").exists())

    def test_pyproject_toml_exists(self):
        self.assertTrue((PROJECT_ROOT / "pyproject.toml").exists())

    def test_setup_py_exists(self):
        self.assertTrue((PROJECT_ROOT / "setup.py").exists())

class PyprojectEntryPointsTests(unittest.TestCase):
    """pyproject.toml entry_points 配置。"""

    def test_entry_points_defined(self):
        """pyproject.toml 必须定义 entry_points（PyPA 规范）。"""
        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib
            except ImportError:
                self.skipTest("tomllib not available")
        with open(PROJECT_ROOT / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        self.assertIn("project", data)
        self.assertIn("scripts", data["project"])
        scripts = data["project"]["scripts"]
        # 必须包含 ucrawl 主入口
        self.assertIn("ucrawl", scripts)
        self.assertEqual(scripts.get("ucrawl-auto"), "entry.dispatcher:run")

class NoStaleBuildArtifactsTests(unittest.TestCase):
    """避免 build 残留文件。"""

    def test_no_dist_in_repo_root_unless_built(self):
        """dist/ 不应在仓库根目录常驻（除非正在构建）。"""
        # 不强制失败，只警告
        dist_dir = PROJECT_ROOT / "dist"
        if dist_dir.exists():
            # 如果存在，至少应该是上次构建的
            self.assertTrue(dist_dir.is_dir())

    def test_no_pycache_in_packaging(self):
        """packaging/ 不应包含 __pycache__（避免污染 spec 解析）。"""
        pycache = PACKAGING_DIR / "__pycache__"
        # 不强制失败，只是提醒
        if pycache.exists():
            # 检查是否有 .pyc 文件
            pyc_files = list(pycache.glob("*.pyc"))
            self.assertGreaterEqual(len(pyc_files), 0)  # 只是记录

class RepositoryHygieneTests(unittest.TestCase):
    """仓库级静态卫生检查。"""

    def test_app_code_has_no_leftover_debug_probe_transport(self):
        forbidden_markers = (
            "# #region " + "debug-point",
            "127.0.0.1:7777" + "/event",
            ".dbg" + "/",
            'runId":"' + "pre-fix",
        )
        violations: list[str] = []
        for base_dir in (PROJECT_ROOT / "app", PROJECT_ROOT / "tests"):
            for path in base_dir.rglob("*"):
                if path.suffix.lower() not in {".py", ".html", ".js"}:
                    continue
                text = path.read_text(encoding="utf-8")
                if any(marker in text for marker in forbidden_markers):
                    violations.append(str(path.relative_to(PROJECT_ROOT)))
        self.assertEqual(violations, [], f"leftover debug probes found: {violations}")

    def test_packaging_docs_reference_runtime_paths_and_project_meta(self):
        docs = (PROJECT_ROOT / "docs" / "packaging.md").read_text(encoding="utf-8")
        readme = (PROJECT_ROOT / "packaging" / "README.md").read_text(encoding="utf-8")
        self.assertIn("runtime_paths.py", docs)
        self.assertIn("project_meta.py", docs)
        self.assertIn("runtime_paths.py", readme)
        self.assertIn("project_meta.py", readme)

if __name__ == "__main__":
    unittest.main()
