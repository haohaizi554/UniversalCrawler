"""WebUI browser cases owned by the responsive layout responsibility."""

from __future__ import annotations


class ResponsiveLayoutCases:
    def test_narrow_shell_keeps_status_bar_visible(self):
        self._goto_ready()
        original_viewport = self._page.viewport_size
        self.addCleanup(
            lambda: original_viewport and self._page.set_viewport_size(original_viewport)
        )
        self._page.set_viewport_size({"width": 640, "height": 760})
        self._page.wait_for_function(
            "document.documentElement.clientWidth === 640 && document.documentElement.clientHeight === 760",
            timeout=5000,
        )

        geometry = self._page.evaluate(
            """
            () => {
              const status = document.querySelector('.status-bar')?.getBoundingClientRect();
              const stack = document.getElementById('rightPanel')?.getBoundingClientRect();
              return {
                statusTop: status?.top || 0,
                statusBottom: status?.bottom || 0,
                statusHeight: status?.height || 0,
                stackBottom: stack?.bottom || 0,
                viewportHeight: window.innerHeight,
                documentOverflow: document.documentElement.scrollWidth - window.innerWidth
              };
            }
            """
        )

        self.assertGreaterEqual(geometry["statusHeight"], 28, geometry)
        self.assertGreaterEqual(geometry["statusTop"], 0, geometry)
        self.assertLessEqual(geometry["statusBottom"], geometry["viewportHeight"], geometry)
        self.assertLessEqual(geometry["stackBottom"], geometry["statusTop"] + 1, geometry)
        self.assertLessEqual(geometry["documentOverflow"], 1, geometry)

    def test_active_narrow_desktop_keeps_title_column_readable(self):
        self._goto_ready()
        original_viewport = self._page.viewport_size
        self.addCleanup(
            lambda: original_viewport and self._page.set_viewport_size(original_viewport)
        )
        self._page.evaluate(
            """
            () => {
              frontendState.active_downloads = [{
                id: 'active-narrow',
                title: 'A production download title that must remain readable at narrow desktop widths',
                platform: 'Bilibili',
                platform_id: 'bilibili',
                progress: 42,
                speed: '8.4 MB/s',
                remaining_time: '00:31',
                status_label: '正在下载',
                detail_fields: [['文件名', 'active-narrow.mp4']]
              }];
              switchPage('active');
              renderActive();
            }
            """
        )

        for width in (1120, 981):
            with self.subTest(width=width):
                self._page.set_viewport_size({"width": width, "height": 760})
                self._page.wait_for_function(
                    "expected => document.documentElement.clientWidth === expected",
                    arg=width,
                    timeout=5000,
                )
                geometry = self._page.evaluate(
                    """
                    () => {
                      const title = document.querySelector('#activeBody tr td:first-child');
                      const detail = document.getElementById('activeDetail');
                      return {
                        titleWidth: title?.getBoundingClientRect().width || 0,
                        titleDisplay: title ? getComputedStyle(title).display : 'missing',
                        detailWidth: detail?.getBoundingClientRect().width || 0,
                        overflow: document.documentElement.scrollWidth - window.innerWidth,
                      };
                    }
                    """
                )
                self.assertGreaterEqual(geometry["titleWidth"], 160, geometry)
                self.assertNotEqual(geometry["titleDisplay"], "none", geometry)
                self.assertGreaterEqual(geometry["detailWidth"], 280, geometry)
                self.assertLessEqual(geometry["overflow"], 1, geometry)

    def test_failed_detail_remains_readable_at_responsive_breakpoint(self):
        self._goto_ready()
        original_viewport = self._page.viewport_size
        self.addCleanup(
            lambda: original_viewport and self._page.set_viewport_size(original_viewport)
        )
        self._page.evaluate(
            """
            () => {
              frontendState.failed_items = [{
                id: 'failed-responsive',
                title: 'Responsive failure detail',
                failed_at: '2026-07-12 18:34:48',
                failed_at_table: '07-12 18:34',
                reason: 'Connection interrupted while reading a long media stream',
                reason_detail_display: 'A detailed failure explanation that must remain visible.',
                display_language: 'en-US',
                platform: 'Bilibili',
                platform_id: 'bilibili',
                trace_id: 'trace-responsive',
                status_label: 'Failed',
                log_excerpt_display_items: [{
                  level: 'ERROR',
                  time_display: '18:34:48',
                  message_display: 'Projected log message'
                }],
                solutions_display: [{
                  title_display: 'Retry the task',
                  description_display: 'Refresh the source link before retrying.'
                }]
              }];
              const appearance = frontendState.settings_snapshot['\u5916\u89c2\u8bbe\u7f6e'] || {};
              appearance.language = 'en-US';
              applyAppearance(appearance);
              switchPage('failed');
              renderFailed();
            }
            """
        )
        self._page.wait_for_selector("#failedBody tr.selected", state="visible", timeout=5000)
        self._page.set_viewport_size({"width": 980, "height": 820})
        self._page.wait_for_function(
            "document.documentElement.clientWidth === 980",
            timeout=5000,
        )

        geometry = self._page.evaluate(
            """
            () => {
              const detail = document.getElementById('failedDetail');
              const solutions = document.getElementById('failedSolutions');
              const clippedHeaders = Array.from(document.querySelectorAll('#page-failed thead th'))
                .filter(cell => cell.scrollWidth > cell.clientWidth + 1)
                .map(cell => cell.textContent.trim());
              const clippedNavigation = Array.from(document.querySelectorAll('.nav-item b'))
                .filter(label => label.scrollWidth > label.clientWidth + 1)
                .map(label => label.textContent.trim());
              const clippedStatuses = Array.from(document.querySelectorAll('#page-failed tbody td:nth-child(4)'))
                .filter(cell => cell.scrollWidth > cell.clientWidth + 1)
                .map(cell => cell.textContent.trim());
              return {
                detailHeight: detail?.getBoundingClientRect().height || 0,
                detailScrollHeight: detail?.scrollHeight || 0,
                solutionHeight: solutions?.getBoundingClientRect().height || 0,
                solutionScrollHeight: solutions?.scrollHeight || 0,
                detailText: detail?.textContent || '',
                solutionText: solutions?.textContent || '',
                clippedHeaders,
                clippedNavigation,
                clippedStatuses,
                overflow: document.documentElement.scrollWidth - window.innerWidth,
              };
            }
            """
        )

        self.assertGreaterEqual(geometry["detailHeight"], 180, geometry)
        self.assertGreaterEqual(geometry["solutionHeight"], 120, geometry)
        self.assertGreaterEqual(geometry["detailHeight"] + 1, geometry["detailScrollHeight"], geometry)
        self.assertGreaterEqual(geometry["solutionHeight"] + 1, geometry["solutionScrollHeight"], geometry)
        self.assertIn("Responsive failure detail", geometry["detailText"])
        self.assertIn("Retry the task", geometry["solutionText"])
        self.assertEqual(geometry["clippedHeaders"], [], geometry)
        self.assertEqual(geometry["clippedNavigation"], [], geometry)
        self.assertEqual(geometry["clippedStatuses"], [], geometry)
        self.assertLessEqual(geometry["overflow"], 1, geometry)
