"""WebUI browser cases owned by the playback responsibility."""

from __future__ import annotations

class PlaybackCases:
    def test_media_surface_tracks_light_dark_and_accent_theme_tokens(self):
        self._goto_ready()
        result = self._page.evaluate(
            """
            () => {
              const video = document.getElementById('videoPlayer');
              const seek = document.getElementById('seekSlider');
              const capture = () => ({
                videoBackground: getComputedStyle(video).backgroundColor,
                seekAccent: getComputedStyle(seek).accentColor,
              });
              applyTheme(false, { accent: 'red' });
              const light = capture();
              applyTheme(true, { accent: 'green' });
              const dark = capture();
              applyAppearance((frontendState.settings_snapshot || {})['外观设置'] || {});
              return { light, dark };
            }
            """
        )

        self.assertEqual(result["light"]["videoBackground"], "rgb(248, 250, 252)")
        self.assertEqual(result["light"]["seekAccent"], "rgb(220, 38, 38)")
        self.assertEqual(result["dark"]["videoBackground"], "rgb(11, 15, 22)")
        self.assertEqual(result["dark"]["seekAccent"], "rgb(34, 197, 94)")

    def test_10_fullscreen_toggle(self):
        """toggleFullscreen 应在 body 上加 is-fullscreen 类。"""
        self._goto_ready()
        result = self._page.evaluate(
            """
            () => {
              const panel = document.getElementById('previewPanel');
              let called = false;
              Object.defineProperty(panel, 'requestFullscreen', {
                configurable: true,
                value: () => {
                  called = true;
                  return Promise.resolve();
                }
              });
              toggleFullscreen();
              return {
                called,
                bodyFullscreen: document.body.classList.contains('is-fullscreen')
              };
            }
            """
        )
        self.assertTrue(result["called"])
        self.assertFalse(result["bodyFullscreen"])

    def test_11ee_playback_controller_uses_public_selection_and_metadata_callbacks(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              const originalFetch = window.fetch;
              const player = document.getElementById('videoPlayer');
              const originalPlay = player.play;
              const originalPause = player.pause;
              const item = Object.freeze({
                id: 'public-video',
                title: 'Public Video',
                filename: 'public-video.mp4',
                local_path: 'D:/public-video.mp4',
                content_type: 'video',
                duration: '--',
                resolution: '--',
                metadata_pending: true
              });
              const state = Object.freeze({
                completed_items: Object.freeze([item]),
                settings_snapshot: Object.freeze({})
              });
              let selectedId = '';
              const metadataPatches = [];
              const actions = [];
              window.fetch = () => Promise.resolve(new Response('', { status: 206 }));
              player.play = () => Promise.resolve();
              player.pause = () => {};
              try {
                window.UcpPlaybackController.configure({
                  getState: () => state,
                  getSelectedCompletedId: () => selectedId,
                  setSelectedCompletedId: id => { selectedId = String(id || ''); },
                  patchCompletedMetadata: (id, metadata) => { metadataPatches.push({ id, metadata }); return true; },
                  t: value => String(value || ''),
                  byId: id => document.getElementById(id),
                  esc,
                  frontendAction: (action, payload) => { actions.push({ action, payload }); },
                  appendLog: () => {},
                  renderCompletedDetail: () => {}
                });
                await window.UcpPlaybackController.playCompleted('public-video');
                Object.defineProperty(player, 'duration', { configurable: true, value: 65 });
                Object.defineProperty(player, 'videoWidth', { configurable: true, value: 1920 });
                Object.defineProperty(player, 'videoHeight', { configurable: true, value: 1080 });
                player.onloadedmetadata();
                return {
                  selectedId,
                  metadataPatches,
                  metadataAction: actions.find(entry => entry.action === 'update_completed_metadata') || null,
                  source: player.getAttribute('src'),
                  originalItem: { duration: item.duration, resolution: item.resolution, pending: item.metadata_pending }
                };
              } finally {
                window.UcpPlaybackController.dispose();
                window.fetch = originalFetch;
                player.play = originalPlay;
                player.pause = originalPause;
                if (typeof configurePlaybackControllerHelpers === 'function') configurePlaybackControllerHelpers();
              }
            }
            """
        )

        self.assertEqual(result["selectedId"], "public-video")
        self.assertEqual(result["source"], "/api/media/public-video")
        self.assertEqual(result["metadataPatches"], [{
            "id": "public-video",
            "metadata": {"duration": "00:01:05", "resolution": "1920 x 1080"},
        }])
        self.assertEqual(result["metadataAction"]["payload"]["source"], "web_player")
        self.assertEqual(result["originalItem"], {"duration": "--", "resolution": "--", "pending": True})

    def test_11ef_playback_controller_ignores_stale_validation_and_media_handlers(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              const originalFetch = window.fetch;
              let resolveOldValidation;
              const selections = [];
              const metadataPatches = [];
              const logs = [];
              const item = id => ({
                id,
                title: id,
                filename: `${id}.mp4`,
                local_path: `D:/${id}.mp4`,
                content_type: 'video'
              });
              const configure = id => window.UcpPlaybackController.configure({
                getState: () => ({ completed_items: [item(id)], settings_snapshot: {} }),
                getSelectedCompletedId: () => selections.at(-1) || '',
                setSelectedCompletedId: value => { selections.push(String(value || '')); },
                patchCompletedMetadata: (sourceId, metadata) => { metadataPatches.push({ sourceId, metadata }); return true; },
                t: value => String(value || ''),
                byId: elementId => document.getElementById(elementId),
                esc,
                frontendAction: () => {},
                appendLog: message => { logs.push(String(message)); },
                renderCompletedDetail: () => {}
              });
              window.fetch = url => String(url).includes('old-video')
                ? new Promise(resolve => { resolveOldValidation = resolve; })
                : Promise.resolve(new Response('', { status: 206 }));
              try {
                configure('old-video');
                const oldPending = window.UcpPlaybackController.playCompleted('old-video');
                await Promise.resolve();
                configure('new-video');
                await window.UcpPlaybackController.playCompleted('new-video');
                const player = document.getElementById('videoPlayer');
                const staleMetadataHandler = player.onloadedmetadata;
                configure('third-video');
                resolveOldValidation(new Response('', { status: 404 }));
                await oldPending;
                Object.defineProperty(player, 'duration', { configurable: true, value: 90 });
                staleMetadataHandler();
                return {
                  selections,
                  metadataPatches,
                  logs,
                  source: player.getAttribute('src')
                };
              } finally {
                window.UcpPlaybackController.dispose();
                window.fetch = originalFetch;
                if (typeof configurePlaybackControllerHelpers === 'function') configurePlaybackControllerHelpers();
              }
            }
            """
        )

        self.assertEqual(result["selections"], ["old-video", "new-video"])
        self.assertEqual(result["metadataPatches"], [])
        self.assertFalse(any("old-video" in message or "文件不存在" in message for message in result["logs"]))
        self.assertIsNone(result["source"])

    def test_11efa_stale_image_timer_cannot_clear_current_run_timer(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              const originalFetch = window.fetch;
              const originalSetTimeout = window.setTimeout;
              const originalClearTimeout = window.clearTimeout;
              const timers = [];
              const cleared = [];
              const selections = [];
              const item = id => ({
                id,
                title: id,
                filename: `${id}.png`,
                local_path: `D:/${id}.png`,
                content_type: 'image'
              });
              const configure = ids => window.UcpPlaybackController.configure({
                getState: () => ({
                  completed_items: ids.map(item),
                  settings_snapshot: { '\u64ad\u653e\u8bbe\u7f6e': { manual_image_switch: false, image_auto_advance_interval_seconds: 1 } }
                }),
                getSelectedCompletedId: () => selections.at(-1) || '',
                setSelectedCompletedId: id => { selections.push(String(id || '')); },
                patchCompletedMetadata: () => false,
                t: value => String(value || ''),
                byId: id => document.getElementById(id),
                esc,
                frontendAction: () => {},
                appendLog: () => {},
                renderCompletedDetail: () => {}
              });
              window.fetch = () => Promise.resolve(new Response('', { status: 206 }));
              window.setTimeout = callback => {
                const timer = { id: timers.length + 1, callback };
                timers.push(timer);
                return timer.id;
              };
              window.clearTimeout = id => { cleared.push(id); };
              try {
                configure(['image-a', 'image-a-next']);
                await window.UcpPlaybackController.playCompleted('image-a');
                const timerA = timers.at(-1);

                configure(['image-b', 'image-b-next']);
                await window.UcpPlaybackController.playCompleted('image-b');
                const timerB = timers.at(-1);

                timerA.callback();
                window.UcpPlaybackController.rescheduleImageAutoAdvance();
                const replacementB = timers.at(-1);
                const timerBWasOwned = cleared.includes(timerB.id);
                window.UcpPlaybackController.dispose();

                return {
                  timerBWasOwned,
                  replacementDisposed: cleared.includes(replacementB.id),
                  selections
                };
              } finally {
                window.UcpPlaybackController.dispose();
                window.fetch = originalFetch;
                window.setTimeout = originalSetTimeout;
                window.clearTimeout = originalClearTimeout;
                if (typeof configurePlaybackControllerHelpers === 'function') configurePlaybackControllerHelpers();
              }
            }
            """
        )

        self.assertTrue(result["timerBWasOwned"])
        self.assertTrue(result["replacementDisposed"])
        self.assertEqual(result["selections"], ["image-a", "image-b"])

    def test_11efaa_image_controls_hide_video_timeline_and_follow_slideshow_setting(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              const originalFetch = window.fetch;
              const originalSetTimeout = window.setTimeout;
              const originalClearTimeout = window.clearTimeout;
              const timers = [];
              const cleared = [];
              const selections = [];
              let fetchCalls = 0;
              const playbackSettings = {
                manual_image_switch: false,
                image_auto_advance_interval_seconds: 3
              };
              const state = {
                completed_items: ['image-a', 'image-b'].map(id => ({
                  id,
                  title: id,
                  filename: `${id}.png`,
                  local_path: `D:/${id}.png`,
                  content_type: 'image'
                })),
                settings_snapshot: { '\u64ad\u653e\u8bbe\u7f6e': playbackSettings }
              };
              switchPage('completed');
              window.fetch = () => {
                fetchCalls += 1;
                return Promise.resolve(new Response('', { status: 206 }));
              };
              window.setTimeout = (callback, delay) => {
                const timer = { id: timers.length + 1, callback, delay };
                timers.push(timer);
                return timer.id;
              };
              window.clearTimeout = id => { cleared.push(id); };
              try {
                window.UcpPlaybackController.configure({
                  getState: () => state,
                  getSelectedCompletedId: () => selections.at(-1) || '',
                  setSelectedCompletedId: id => { selections.push(String(id || '')); },
                  patchCompletedMetadata: () => false,
                  t: value => String(value || ''),
                  byId: id => document.getElementById(id),
                  esc,
                  frontendAction: () => {},
                  appendLog: () => {},
                  renderCompletedDetail: () => {}
                });
                await window.UcpPlaybackController.playCompleted('image-a');
                const button = document.getElementById('playBtn');
                const seek = document.getElementById('seekSlider');
                const time = document.getElementById('timeLabel');
                const controls = document.getElementById('mediaControls').getBoundingClientRect();
                const fullscreen = document.getElementById('fullscreenBtn').getBoundingClientRect();
                const firstTimer = timers.at(-1);
                const initial = {
                  seekHidden: seek.hidden,
                  seekDisplay: getComputedStyle(seek).display,
                  timeHidden: time.hidden,
                  timeDisplay: getComputedStyle(time).display,
                  buttonDisabled: button.disabled,
                  buttonTitle: button.title,
                  timerDelay: firstTimer && firstTimer.delay,
                  fullscreenWidth: Math.round(fullscreen.width),
                  fullscreenRightGap: Math.round(controls.right - fullscreen.right)
                };

                window.UcpPlaybackController.togglePlay();
                const paused = {
                  timerCleared: cleared.includes(firstTimer.id),
                  buttonTitle: button.title
                };

                window.UcpPlaybackController.togglePlay();
                const resumedTimer = timers.at(-1);
                const resumed = {
                  timerRearmed: resumedTimer !== firstTimer,
                  buttonTitle: button.title
                };

                playbackSettings.manual_image_switch = true;
                renderFrontendSections(new Set(['settings_snapshot']));
                const manual = {
                  timerCleared: cleared.includes(resumedTimer.id),
                  buttonDisabled: button.disabled,
                  buttonTitle: button.title
                };
                return { initial, paused, resumed, manual, fetchCalls };
              } finally {
                window.UcpPlaybackController.dispose();
                window.fetch = originalFetch;
                window.setTimeout = originalSetTimeout;
                window.clearTimeout = originalClearTimeout;
                if (typeof configurePlaybackControllerHelpers === 'function') configurePlaybackControllerHelpers();
              }
            }
            """
        )

        self.assertEqual(result["initial"], {
            "seekHidden": True,
            "seekDisplay": "none",
            "timeHidden": True,
            "timeDisplay": "none",
            "buttonDisabled": False,
            "buttonTitle": "暂停",
            "timerDelay": 3000,
            "fullscreenWidth": 76,
            "fullscreenRightGap": 15,
        })
        self.assertEqual(result["paused"], {"timerCleared": True, "buttonTitle": "播放"})
        self.assertEqual(result["resumed"], {"timerRearmed": True, "buttonTitle": "暂停"})
        self.assertEqual(result["manual"], {
            "timerCleared": True,
            "buttonDisabled": True,
            "buttonTitle": "播放",
        })
        self.assertEqual(result["fetchCalls"], 1)

    def test_11efab_image_slideshow_wraps_and_single_item_does_not_fake_running(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              const originalFetch = window.fetch;
              const originalSetTimeout = window.setTimeout;
              const originalClearTimeout = window.clearTimeout;
              const timers = [];
              const cleared = [];
              const selections = [];
              let activeState;
              const image = id => ({
                id,
                title: id,
                filename: `${id}.png`,
                local_path: `D:/${id}.png`,
                content_type: 'image'
              });
              const configure = () => window.UcpPlaybackController.configure({
                getState: () => activeState,
                getSelectedCompletedId: () => selections.at(-1) || '',
                setSelectedCompletedId: id => { selections.push(String(id || '')); },
                patchCompletedMetadata: () => false,
                t: value => String(value || ''),
                byId: id => document.getElementById(id),
                esc,
                frontendAction: () => {},
                appendLog: () => {},
                renderCompletedDetail: () => {}
              });
              window.fetch = () => Promise.resolve(new Response('', { status: 206 }));
              window.setTimeout = (callback, delay) => {
                const timer = { id: timers.length + 1, callback, delay };
                timers.push(timer);
                return timer.id;
              };
              window.clearTimeout = id => { cleared.push(id); };
              try {
                activeState = {
                  completed_items: [
                    image('single'),
                    {
                      id: 'video-only-neighbor',
                      title: 'video-only-neighbor',
                      filename: 'video.mp4',
                      local_path: 'D:/video.mp4',
                      content_type: 'video'
                    }
                  ],
                  settings_snapshot: { '\u64ad\u653e\u8bbe\u7f6e': { manual_image_switch: false } }
                };
                configure();
                await window.UcpPlaybackController.playCompleted('single');
                const button = document.getElementById('playBtn');
                const single = {
                  timerCount: timers.length,
                  buttonDisabled: button.disabled,
                  buttonTitle: button.title
                };

                activeState.completed_items.push(image('added-later'));
                renderFrontendSections(new Set(['completed_items']));
                const expandedTimer = timers.at(-1);
                const expanded = {
                  timerStarted: timers.length === 1,
                  buttonDisabled: button.disabled,
                  buttonTitle: button.title
                };

                activeState.completed_items.pop();
                renderFrontendSections(new Set(['completed_items']));
                const contracted = {
                  timerCleared: cleared.includes(expandedTimer.id),
                  buttonDisabled: button.disabled,
                  buttonTitle: button.title
                };

                activeState = {
                  completed_items: [
                    image('image-a'),
                    {
                      id: 'video-between-images',
                      title: 'video-between-images',
                      filename: 'between.mp4',
                      local_path: 'D:/between.mp4',
                      content_type: 'video'
                    },
                    image('image-b')
                  ],
                  settings_snapshot: { '\u64ad\u653e\u8bbe\u7f6e': { manual_image_switch: false } }
                };
                configure();
                await window.UcpPlaybackController.playCompleted('image-b');
                const lastTimer = timers.at(-1);
                lastTimer.callback();
                await new Promise(resolve => originalSetTimeout(resolve, 0));
                return {
                  single,
                  expanded,
                  contracted,
                  wrappedTo: selections.at(-1),
                  timerRearmed: timers.at(-1) !== lastTimer
                };
              } finally {
                window.UcpPlaybackController.dispose();
                window.fetch = originalFetch;
                window.setTimeout = originalSetTimeout;
                window.clearTimeout = originalClearTimeout;
                if (typeof configurePlaybackControllerHelpers === 'function') configurePlaybackControllerHelpers();
              }
            }
            """
        )

        self.assertEqual(result["single"], {
            "timerCount": 0,
            "buttonDisabled": True,
            "buttonTitle": "播放",
        })
        self.assertEqual(result["expanded"], {
            "timerStarted": True,
            "buttonDisabled": False,
            "buttonTitle": "暂停",
        })
        self.assertEqual(result["contracted"], {
            "timerCleared": True,
            "buttonDisabled": True,
            "buttonTitle": "播放",
        })
        self.assertEqual(result["wrappedTo"], "image-a")
        self.assertTrue(result["timerRearmed"])

    def test_11efb_stale_fullscreen_request_exits_when_current_run_has_no_owner(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              const panel = document.getElementById('previewPanel');
              const originalRequestFullscreen = panel.requestFullscreen;
              const originalExitFullscreen = document.exitFullscreen;
              const fullscreenDescriptor = Object.getOwnPropertyDescriptor(document, 'fullscreenElement');
              let resolveRequestA;
              let fullscreenElement = null;
              let exitCalls = 0;
              const configure = () => window.UcpPlaybackController.configure({
                getState: () => ({ completed_items: [], settings_snapshot: {} }),
                getSelectedCompletedId: () => '',
                setSelectedCompletedId: () => {},
                patchCompletedMetadata: () => false,
                t: value => String(value || ''),
                byId: id => document.getElementById(id),
                esc,
                frontendAction: () => {},
                appendLog: () => {},
                renderCompletedDetail: () => {}
              });
              Object.defineProperty(document, 'fullscreenElement', {
                configurable: true,
                get: () => fullscreenElement
              });
              panel.requestFullscreen = () => new Promise(resolve => {
                resolveRequestA = () => {
                  fullscreenElement = panel;
                  resolve();
                };
              });
              document.exitFullscreen = () => {
                exitCalls += 1;
                fullscreenElement = null;
                return Promise.resolve();
              };
              try {
                configure();
                const requestA = window.UcpPlaybackController.toggleFullscreen();
                configure();

                resolveRequestA();
                await requestA;
                const afterStaleA = {
                  active: fullscreenElement === panel,
                  exitCalls
                };

                window.UcpPlaybackController.dispose();
                window.UcpPlaybackController.dispose();
                return {
                  afterStaleA,
                  activeAfterDispose: fullscreenElement === panel,
                  exitCalls
                };
              } finally {
                window.UcpPlaybackController.dispose();
                panel.requestFullscreen = originalRequestFullscreen;
                document.exitFullscreen = originalExitFullscreen;
                if (fullscreenDescriptor) Object.defineProperty(document, 'fullscreenElement', fullscreenDescriptor);
                else delete document.fullscreenElement;
                if (typeof configurePlaybackControllerHelpers === 'function') configurePlaybackControllerHelpers();
              }
            }
            """
        )

        self.assertFalse(result["afterStaleA"]["active"])
        self.assertEqual(result["afterStaleA"]["exitCalls"], 1)
        self.assertFalse(result["activeAfterDispose"])
        self.assertEqual(result["exitCalls"], 1)

    def test_11efc_stale_fullscreen_request_cannot_exit_current_run_fullscreen(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              const panel = document.getElementById('previewPanel');
              const originalRequestFullscreen = panel.requestFullscreen;
              const originalExitFullscreen = document.exitFullscreen;
              const fullscreenDescriptor = Object.getOwnPropertyDescriptor(document, 'fullscreenElement');
              const requests = [];
              let fullscreenElement = null;
              let exitCalls = 0;
              const configure = () => window.UcpPlaybackController.configure({
                getState: () => ({ completed_items: [], settings_snapshot: {} }),
                getSelectedCompletedId: () => '',
                setSelectedCompletedId: () => {},
                patchCompletedMetadata: () => false,
                t: value => String(value || ''),
                byId: id => document.getElementById(id),
                esc,
                frontendAction: () => {},
                appendLog: () => {},
                renderCompletedDetail: () => {}
              });
              Object.defineProperty(document, 'fullscreenElement', {
                configurable: true,
                get: () => fullscreenElement
              });
              panel.requestFullscreen = () => new Promise(resolve => {
                requests.push(() => {
                  fullscreenElement = panel;
                  resolve();
                });
              });
              document.exitFullscreen = () => {
                exitCalls += 1;
                fullscreenElement = null;
                return Promise.resolve();
              };
              try {
                configure();
                const requestA = window.UcpPlaybackController.toggleFullscreen();
                configure();
                const requestB = window.UcpPlaybackController.toggleFullscreen();

                requests[1]();
                await requestB;
                requests[0]();
                await requestA;
                const afterStaleA = {
                  active: fullscreenElement === panel,
                  exitCalls
                };

                window.UcpPlaybackController.dispose();
                await Promise.resolve();
                return {
                  afterStaleA,
                  activeAfterDispose: fullscreenElement === panel,
                  exitCalls
                };
              } finally {
                window.UcpPlaybackController.dispose();
                panel.requestFullscreen = originalRequestFullscreen;
                document.exitFullscreen = originalExitFullscreen;
                if (fullscreenDescriptor) Object.defineProperty(document, 'fullscreenElement', fullscreenDescriptor);
                else delete document.fullscreenElement;
                if (typeof configurePlaybackControllerHelpers === 'function') configurePlaybackControllerHelpers();
              }
            }
            """
        )

        self.assertTrue(result["afterStaleA"]["active"])
        self.assertEqual(result["afterStaleA"]["exitCalls"], 0)
        self.assertFalse(result["activeAfterDispose"])
        self.assertEqual(result["exitCalls"], 1)

    def test_11eg_playback_controller_dispose_is_idempotent_and_cancels_image_advance(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              const originalFetch = window.fetch;
              const originalSetTimeout = window.setTimeout;
              const originalClearTimeout = window.clearTimeout;
              const timers = [];
              const cleared = [];
              const selections = [];
              const state = {
                completed_items: ['image-a', 'image-b'].map(id => ({
                  id,
                  title: id,
                  filename: `${id}.png`,
                  local_path: `D:/${id}.png`,
                  content_type: 'image'
                })),
                settings_snapshot: { '\u64ad\u653e\u8bbe\u7f6e': { manual_image_switch: false, image_auto_advance_interval_seconds: 1 } }
              };
              window.fetch = () => Promise.resolve(new Response('', { status: 206 }));
              window.setTimeout = callback => {
                const timer = { id: timers.length + 1, callback };
                timers.push(timer);
                return timer.id;
              };
              window.clearTimeout = id => { cleared.push(id); };
              try {
                window.UcpPlaybackController.configure({
                  getState: () => state,
                  getSelectedCompletedId: () => selections.at(-1) || '',
                  setSelectedCompletedId: id => { selections.push(String(id || '')); },
                  patchCompletedMetadata: () => false,
                  t: value => String(value || ''),
                  byId: id => document.getElementById(id),
                  esc,
                  frontendAction: () => {},
                  appendLog: () => {},
                  renderCompletedDetail: () => {}
                });
                await window.UcpPlaybackController.playCompleted('image-a');
                const scheduled = timers[0];
                window.UcpPlaybackController.dispose();
                window.UcpPlaybackController.dispose();
                scheduled.callback();
                const player = document.getElementById('videoPlayer');
                return {
                  selections,
                  timerCleared: cleared.includes(scheduled.id),
                  source: player.getAttribute('src'),
                  videoDisplay: player.style.display,
                  previewHasImage: Boolean(document.querySelector('#previewArea .preview-image'))
                };
              } finally {
                window.UcpPlaybackController.dispose();
                window.fetch = originalFetch;
                window.setTimeout = originalSetTimeout;
                window.clearTimeout = originalClearTimeout;
                if (typeof configurePlaybackControllerHelpers === 'function') configurePlaybackControllerHelpers();
              }
            }
            """
        )

        self.assertEqual(result["selections"], ["image-a"])
        self.assertTrue(result["timerCleared"])
        self.assertIsNone(result["source"])
        self.assertEqual(result["videoDisplay"], "none")
        self.assertFalse(result["previewHasImage"])

    def test_11eh_pending_playback_delete_invalidates_validation_continuation(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              const originalFetch = window.fetch;
              const player = document.getElementById('videoPlayer');
              const originalPlay = player.play;
              const originalPause = player.pause;
              let resolveValidation;
              let selectedId = '';
              let playCalls = 0;
              const actions = [];
              const metadataPatches = [];
              const state = {
                completed_items: [{
                  id: 'pending-delete',
                  title: 'Pending Delete',
                  filename: 'pending-delete.mp4',
                  local_path: 'D:/pending-delete.mp4',
                  content_type: 'video'
                }],
                settings_snapshot: {}
              };
              window.fetch = () => new Promise(resolve => { resolveValidation = resolve; });
              player.play = () => { playCalls += 1; return Promise.resolve(); };
              player.pause = () => {};
              try {
                window.UcpPlaybackController.configure({
                  getState: () => state,
                  getSelectedCompletedId: () => selectedId,
                  setSelectedCompletedId: id => { selectedId = String(id || ''); },
                  patchCompletedMetadata: (id, metadata) => { metadataPatches.push({ id, metadata }); return true; },
                  t: value => String(value || ''),
                  byId: id => document.getElementById(id),
                  esc,
                  frontendAction: (action, payload) => {
                    actions.push({ action, payload });
                    if (action === 'delete_item') state.completed_items = [];
                  },
                  appendLog: () => {},
                  renderCompletedDetail: () => {}
                });
                const pendingPlay = window.UcpPlaybackController.playCompleted('pending-delete');
                await Promise.resolve();
                window.UcpPlaybackController.deleteVideo('pending-delete');
                resolveValidation(new Response('', { status: 206 }));
                const playResult = await pendingPlay;
                return {
                  playResult,
                  selectedId,
                  playCalls,
                  actions,
                  metadataPatches,
                  source: player.getAttribute('src'),
                  videoDisplay: player.style.display,
                  previewHasImage: Boolean(document.querySelector('#previewArea .preview-image'))
                };
              } finally {
                window.UcpPlaybackController.dispose();
                window.fetch = originalFetch;
                player.play = originalPlay;
                player.pause = originalPause;
                if (typeof configurePlaybackControllerHelpers === 'function') configurePlaybackControllerHelpers();
              }
            }
            """
        )

        self.assertFalse(result["playResult"])
        self.assertEqual(result["selectedId"], "pending-delete")
        self.assertEqual(result["playCalls"], 0)
        self.assertEqual(result["actions"], [{"action": "delete_item", "payload": {"id": "pending-delete"}}])
        self.assertEqual(result["metadataPatches"], [])
        self.assertIsNone(result["source"])
        self.assertEqual(result["videoDisplay"], "none")
        self.assertFalse(result["previewHasImage"])

    def test_11ei_playback_reloads_item_after_media_validation(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              const originalFetch = window.fetch;
              const player = document.getElementById('videoPlayer');
              const originalPlay = player.play;
              const originalPause = player.pause;
              let resolveValidation;
              let selectedId = '';
              let playCalls = 0;
              const state = {
                completed_items: [{
                  id: 'removed-during-validation',
                  title: 'Removed During Validation',
                  filename: 'removed.mp4',
                  local_path: 'D:/removed.mp4',
                  content_type: 'video'
                }],
                settings_snapshot: {}
              };
              window.fetch = () => new Promise(resolve => { resolveValidation = resolve; });
              player.play = () => { playCalls += 1; return Promise.resolve(); };
              player.pause = () => {};
              try {
                window.UcpPlaybackController.configure({
                  getState: () => state,
                  getSelectedCompletedId: () => selectedId,
                  setSelectedCompletedId: id => { selectedId = String(id || ''); },
                  patchCompletedMetadata: () => false,
                  t: value => String(value || ''),
                  byId: id => document.getElementById(id),
                  esc,
                  frontendAction: () => {},
                  appendLog: () => {},
                  renderCompletedDetail: () => {}
                });
                const pendingPlay = window.UcpPlaybackController.playCompleted('removed-during-validation');
                await Promise.resolve();
                state.completed_items = [];
                resolveValidation(new Response('', { status: 206 }));
                const playResult = await pendingPlay;
                return {
                  playResult,
                  selectedId,
                  playCalls,
                  source: player.getAttribute('src'),
                  videoDisplay: player.style.display
                };
              } finally {
                window.UcpPlaybackController.dispose();
                window.fetch = originalFetch;
                player.play = originalPlay;
                player.pause = originalPause;
                if (typeof configurePlaybackControllerHelpers === 'function') configurePlaybackControllerHelpers();
              }
            }
            """
        )

        self.assertFalse(result["playResult"])
        self.assertEqual(result["selectedId"], "removed-during-validation")
        self.assertEqual(result["playCalls"], 0)
        self.assertIsNone(result["source"])
        self.assertEqual(result["videoDisplay"], "none")

    def test_11ej_fullscreen_completion_after_dispose_exits_without_dom_write(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              const panel = document.getElementById('previewPanel');
              const button = document.getElementById('fullscreenBtn');
              const originalRequestFullscreen = panel.requestFullscreen;
              const originalExitFullscreen = document.exitFullscreen;
              const fullscreenDescriptor = Object.getOwnPropertyDescriptor(document, 'fullscreenElement');
              let fullscreenElement = null;
              let resolveRequest;
              let exitCalls = 0;
              const logs = [];
              Object.defineProperty(document, 'fullscreenElement', {
                configurable: true,
                get: () => fullscreenElement
              });
              panel.requestFullscreen = () => new Promise(resolve => {
                resolveRequest = () => {
                  fullscreenElement = panel;
                  resolve();
                };
              });
              document.exitFullscreen = () => {
                exitCalls += 1;
                fullscreenElement = null;
                return Promise.resolve();
              };
              try {
                window.UcpPlaybackController.configure({
                  getState: () => ({ completed_items: [], settings_snapshot: {} }),
                  getSelectedCompletedId: () => '',
                  setSelectedCompletedId: () => {},
                  patchCompletedMetadata: () => false,
                  t: value => String(value || ''),
                  byId: id => document.getElementById(id),
                  esc,
                  frontendAction: () => {},
                  appendLog: message => { logs.push(String(message)); },
                  renderCompletedDetail: () => {}
                });
                const request = window.UcpPlaybackController.toggleFullscreen();
                window.UcpPlaybackController.dispose();
                button.textContent = 'disposed-marker';
                resolveRequest();
                if (request && typeof request.then === 'function') await request;
                await Promise.resolve();
                return {
                  exitCalls,
                  fullscreenActive: fullscreenElement === panel,
                  buttonText: button.textContent,
                  panelFullscreenClass: panel.classList.contains('is-fullscreen'),
                  logs
                };
              } finally {
                window.UcpPlaybackController.dispose();
                panel.requestFullscreen = originalRequestFullscreen;
                document.exitFullscreen = originalExitFullscreen;
                if (fullscreenDescriptor) Object.defineProperty(document, 'fullscreenElement', fullscreenDescriptor);
                else delete document.fullscreenElement;
                if (typeof configurePlaybackControllerHelpers === 'function') configurePlaybackControllerHelpers();
              }
            }
            """
        )

        self.assertEqual(result["exitCalls"], 1)
        self.assertFalse(result["fullscreenActive"])
        self.assertEqual(result["buttonText"], "disposed-marker")
        self.assertFalse(result["panelFullscreenClass"])
        self.assertEqual(result["logs"], [])

    def test_11ek_fullscreen_sync_failure_is_reported_without_throwing(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              const panel = document.getElementById('previewPanel');
              const originalRequestFullscreen = panel.requestFullscreen;
              const logs = [];
              panel.requestFullscreen = () => { throw new Error('sync fullscreen failure'); };
              try {
                window.UcpPlaybackController.configure({
                  getState: () => ({ completed_items: [], settings_snapshot: {} }),
                  getSelectedCompletedId: () => '',
                  setSelectedCompletedId: () => {},
                  patchCompletedMetadata: () => false,
                  t: value => String(value || ''),
                  byId: id => document.getElementById(id),
                  esc,
                  frontendAction: () => {},
                  appendLog: message => { logs.push(String(message)); },
                  renderCompletedDetail: () => {}
                });
                let threw = false;
                try { window.UcpPlaybackController.toggleFullscreen(); } catch (_error) { threw = true; }
                return { threw, logs };
              } finally {
                window.UcpPlaybackController.dispose();
                panel.requestFullscreen = originalRequestFullscreen;
                if (typeof configurePlaybackControllerHelpers === 'function') configurePlaybackControllerHelpers();
              }
            }
            """
        )

        self.assertFalse(result["threw"])
        self.assertTrue(any("sync fullscreen failure" in message for message in result["logs"]))

    def test_11f_missing_media_validation_keeps_preview_closed(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              window.__isolateFrontendStateForTest();
              const originalFetch = window.fetch.bind(window);
              window.fetch = (url, options) => {
                if (String(url).includes('/api/media/missing-media')) {
                  return Promise.resolve(new Response('', { status: 404 }));
                }
                return originalFetch(url, options);
              };
              try {
                frontendState.completed_items = [{
                  id: 'missing-media',
                  title: 'Missing Demo',
                  filename: 'missing.mp4',
                  local_path: 'Z:/missing.mp4',
                  content_type: 'video',
                  format: 'MP4'
                }];
                currentPage = 'completed';
                renderCompleted();
                await window.UcpPlaybackController.playCompleted('missing-media');
                return {
                  selectedId: selected.completed,
                  source: document.getElementById('videoPlayer').getAttribute('src'),
                  videoDisplay: document.getElementById('videoPlayer').style.display,
                  previewDisplay: document.getElementById('previewArea').style.display,
                  logs: (frontendState.log_items || []).slice(-4).map(item => item.message)
                };
              } finally {
                window.fetch = originalFetch;
              }
            }
            """
        )

        self.assertEqual(result["selectedId"], "missing-media")
        self.assertIsNone(result["source"])
        self.assertNotEqual(result["videoDisplay"], "block")
        self.assertNotEqual(result["previewDisplay"], "none")
        self.assertTrue(
            any("文件不存在" in message for message in result["logs"]),
            f"expected missing-file log, got {result['logs']!r}",
        )

    def test_11e_delete_current_preview_closes_player_immediately(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              window.__isolateFrontendStateForTest();
              const originalFetch = window.fetch.bind(window);
              const player = document.getElementById('videoPlayer');
              window.fetch = () => Promise.resolve(new Response(JSON.stringify({ status: 'ok' }), {
                status: 200,
                headers: { 'content-type': 'application/json' }
              }));
              try {
                ws = null;
                frontendState.completed_items = [{
                  id: 'playing-delete',
                  title: 'Playing Delete',
                  filename: 'playing-delete.png',
                  local_path: 'Z:/playing-delete.png',
                  content_type: 'image',
                  format: 'PNG'
                }];
                currentPage = 'completed';
                const preview = document.getElementById('previewArea');
                await window.UcpPlaybackController.playCompleted('playing-delete');
                const openedImage = Boolean(preview.querySelector('.preview-image'));
                frontendAction('delete_item', { id: 'playing-delete' });
                await new Promise(resolve => setTimeout(resolve, 0));
                return {
                  openedImage,
                  source: player.getAttribute('src'),
                  videoDisplay: player.style.display,
                  previewDisplay: preview.style.display,
                  previewText: preview.textContent,
                  previewHasImage: Boolean(preview.querySelector('.preview-image'))
                };
              } finally {
                window.fetch = originalFetch;
              }
            }
            """
        )

        self.assertTrue(result["openedImage"])
        self.assertIsNone(result["source"])
        self.assertEqual(result["videoDisplay"], "none")
        self.assertEqual(result["previewDisplay"], "flex")
        self.assertEqual(result["previewText"], "")
        self.assertFalse(result["previewHasImage"])
