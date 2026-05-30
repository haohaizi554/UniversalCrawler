# 自动化命令执行结果

以下结果可直接用于课程报告引用，也可作为后续截图时的命令依据。

## discover

- 命令：`python -m unittest discover -s tests`
- 退出码：`0`
- 输出文件：`coursework/command_outputs/discover.txt`

```text
...................................................................................................................................................................................................................
----------------------------------------------------------------------
Ran 211 tests in 10.699s
OK
```

## run_core_suite

- 命令：`python tests/run_core_suite.py`
- 退出码：`0`
- 输出文件：`coursework/command_outputs/run_core_suite.txt`

```text
test_main_logs_error_message_and_reraises_startup_failure (tests.test_main_entry.MainEntryTests.test_main_logs_error_message_and_reraises_startup_failure) ... ok
test_set_windows_app_user_model_id_is_noop_on_non_windows (tests.test_main_entry.MainEntryTests.test_set_windows_app_user_model_id_is_noop_on_non_windows) ... ok
test_set_windows_app_user_model_id_swallows_ctypes_errors (tests.test_main_entry.MainEntryTests.test_set_windows_app_user_model_id_swallows_ctypes_errors) ... ok
----------------------------------------------------------------------
Ran 175 tests in 10.006s
OK
```

## test_utils_filenames

- 命令：`python -m unittest tests.test_utils_filenames`
- 退出码：`0`
- 输出文件：`coursework/command_outputs/test_utils_filenames.txt`

```text
.....
----------------------------------------------------------------------
Ran 5 tests in 0.000s
OK
```

## test_runtime_paths

- 命令：`python -m unittest tests.test_runtime_paths`
- 退出码：`0`
- 输出文件：`coursework/command_outputs/test_runtime_paths.txt`

```text
......
----------------------------------------------------------------------
Ran 6 tests in 1.240s
OK
```

## test_integration_flows

- 命令：`python -m unittest tests.test_integration_flows`
- 退出码：`0`
- 输出文件：`coursework/command_outputs/test_integration_flows.txt`

```text
...
----------------------------------------------------------------------
Ran 3 tests in 0.497s
OK
```

## test_main_window

- 命令：`python -m unittest tests.test_main_window`
- 退出码：`0`
- 输出文件：`coursework/command_outputs/test_main_window.txt`

```text
..........
----------------------------------------------------------------------
Ran 10 tests in 0.006s
OK
```

## test_download_queue_panel

- 命令：`python -m unittest tests.test_download_queue_panel`
- 退出码：`0`
- 输出文件：`coursework/command_outputs/test_download_queue_panel.txt`

```text
......
----------------------------------------------------------------------
Ran 6 tests in 0.123s
OK
```

