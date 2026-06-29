# UI Icon Manifest

This directory is the canonical icon asset set for the PyQt6 GUI and WebUI.
The current organization is based on the existing image files in `UI/icon`.

WebUI serves these files through `/ui-icon/{name}`. The GUI loads them through
`app.utils.qt_runtime.load_qt_icon`.

## Naming Rules

- `nav_*`: sidebar navigation icons.
- `action_*`: toolbar, table, and detail-panel actions.
- `status_*`: runtime, queue, and diagnostic states.
- `tool_*`: toolbox cards.
- `log_level_*`: log level badges.
- `platform_*`: generic platform fallback icons.
- Platform brand icons are protected and must not be overwritten.

## Protected Platform Icons

| File | Meaning | Usage |
| --- | --- | --- |
| `platform_douyin.png` | Douyin | Platform selector and platform badges |
| `platform_bilibili.png` | Bilibili | Platform selector and platform badges |
| `platform_kuaishou.png` | Kuaishou | Platform selector and platform badges |
| `platform_missav.png` | MissAV | Platform selector and platform badges |
| `platform_xiaohongshu.png` | Xiaohongshu | Platform selector and platform badges |
| `platform_web.png` | Generic web platform | Fallback for unknown platforms |

## Sidebar Navigation

| File | Meaning | Usage |
| --- | --- | --- |
| `nav_download_queue.png` | Download queue | Left navigation: download queue page |
| `nav_downloading.png` | Downloading | Left navigation: active downloads page |
| `nav_completed.png` | Completed | Left navigation: completed page |
| `nav_failed.png` | Failed | Left navigation: failed list page |
| `nav_log_center.png` | Logs | Left navigation: log center page |
| `nav_settings.png` | Settings | Left navigation: configuration center page |
| `nav_toolbox.png` | Toolbox | Left navigation: toolbox page |

## Actions

| File | Meaning | Usage |
| --- | --- | --- |
| `action_play.png` | Play/start | Start task and playback actions |
| `action_pause.png` | Pause | Pause-style control where available |
| `action_stop.png` | Stop/pause control | Stop task button until a true stop-square asset is available |
| `action_open_directory.png` | Open directory | Change/open directory actions |
| `action_delete.png` | Delete | Neutral delete action |
| `action_delete_red.png` | Destructive delete | Dangerous delete action |
| `action_copy.png` | Copy | Copy diagnostics or Trace ID |
| `action_refresh.png` | Refresh/retry | Refresh, retry, and conversion source visual |
| `action_search.png` | Search/scan | Filters and duplicate scan source visual |
| `action_trace_link.png` | Link/Trace | Trace/source link fields |
| `action_view_details.png` | Details | Detail and metadata source visual |
| `action_download.png` | Download | Download action and active-download source visual |
| `action_upload.png` | Upload/export | Upload speed and export-style actions |
| `action_arrow_right.png` | Drill-in | Detail navigation and card affordance |
| `action_code.png` | Code/JSON | Structured diagnostics |
| `action_help.png` | Help | Possible solutions and help hints |
| `action_move_down.png` | Move down | Ordering or collapse affordance |
| `action_next.png` | Next | Media next item |
| `action_previous.png` | Previous | Media previous item |
| `action_repair.png` | Repair | Troubleshooting and repair tools |
| `action_theme_light.png` | Light theme | Theme control |
| `action_theme_night.png` | Dark theme | Theme control |
| `action_theme_palette.png` | Theme palette | Appearance settings |
| `action_user.png` | User/account | Account or identity fields |

## Status And Logs

| File | Meaning | Usage |
| --- | --- | --- |
| `status_success.png` | Success | Generic success/completed state |
| `status_failed.png` | Failed | Generic failed state |
| `status_running.png` | Running | Running app/task state |
| `status_pending.png` | Pending | Pending or waiting state |
| `status_merging.png` | Merging | Segment merge state |
| `status_timeout.png` | Timeout | Timeout or remaining-time state |
| `status_warning.png` | Warning | Non-fatal warning state |
| `status_error_warning.png` | Error warning | Error diagnostics warning state |
| `status_network_warning.png` | Network/source warning | Network, source, or platform warning state |
| `status_locked.png` | Locked | Permission or login required state |
| `log_level_info.png` | INFO | INFO log badge |
| `log_level_warn.png` | WARN | WARN log badge |
| `log_level_error.png` | ERROR | ERROR log badge |

## Toolbox Cards

| File | Meaning | Usage |
| --- | --- | --- |
| `tool_link_parser.png` | Link parsing | Toolbox: link parser |
| `tool_batch_rename.png` | Batch rename | Toolbox: batch rename |
| `tool_cover_extract.png` | Cover extraction | Toolbox: cover extraction |
| `tool_video_to_audio.png` | Video to audio | Toolbox: video-to-audio conversion |
| `tool_duplicate_scan.png` | Duplicate scan | Toolbox: local duplicate scan |
| `tool_metadata_view.png` | Metadata viewer | Toolbox: metadata viewer |
| `tool_format_convert.png` | Format conversion | Toolbox: format conversion |
| `tool_file_verify.png` | File verification | Toolbox: file checksum/verification |

## View Icons

| File | Meaning | Usage |
| --- | --- | --- |
| `view_grid.png` | Grid view | Dense/card view fallback |

## Managed From Existing Assets

These semantic files intentionally reuse current visuals from this directory.

| Semantic file | Source file | Reason |
| --- | --- | --- |
| `nav_downloading.png` | `action_download.png` | Separate navigation semantic from the shared action icon |
| `action_pause.png` | `action_stop.png` | The available stop asset is visually a pause control |
| `status_success.png` | `nav_completed.png` | Separate generic status semantic from navigation |
| `status_failed.png` | `nav_failed.png` | Separate generic status semantic from navigation |
| `tool_link_parser.png` | `action_trace_link.png` | Existing link visual fits the link parser card |
| `tool_duplicate_scan.png` | `action_search.png` | Existing search visual fits duplicate scanning |
| `tool_metadata_view.png` | `action_view_details.png` | Existing details visual fits metadata viewing |
| `tool_format_convert.png` | `action_refresh.png` | Existing refresh visual fits format conversion |
| `status_network_warning.png` | `tool_cover_extract_small.png` | The image is visually a network/source warning, not a cover tool |

## Missing Or Deferred

| Requested semantic | Status | Note |
| --- | --- | --- |
| True stop-square icon | Deferred | Current available `action_stop.png` is pause-style; code keeps the stable stop semantic for the stop task button |

## Current Code Reference Check

The GUI/WebUI/service references currently resolve to files in this directory.
Run a static reference check after changing names.

Last managed update: existing `UI/icon` assets only; no platform brand icon was
overwritten.
