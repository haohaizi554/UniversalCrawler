"""WebUI browser cases owned by the dialogs and keyboard responsibility."""

from __future__ import annotations

class DialogsAndKeyboardCases:
    def test_11_esc_closes_modals(self):
        """Esc 键应关闭弹窗。"""
        self._goto_ready()
        # 打开 selection modal
        self._page.evaluate("showSelectionModal([{title: 'x'}])")
        self._page.wait_for_function(
            "() => ['flex', 'block'].includes(document.getElementById('selectionModal')?.style.display)",
            timeout=5000,
        )
        # 按 Esc
        self._page.keyboard.press("Escape")
        self._page.wait_for_function(
            "() => ['', 'none'].includes(document.getElementById('selectionModal')?.style.display)",
            timeout=5000,
        )
        # modal 应隐藏
        display = self._page.evaluate("document.getElementById('selectionModal').style.display")
        self.assertIn(display, ("none", ""), f"selectionModal should be hidden, got display={display!r}")

    def test_11b_enter_confirms_selection_modal(self):
        self._goto_ready()
        self._page.evaluate(
            """
            () => {
              window.__selectionShortcutMessages = [];
              window.sendWS = (type, payload) => window.__selectionShortcutMessages.push({ type, payload });
              sendWS = window.sendWS;
              showSelectionModal([{title: 'first'}, {title: 'second'}]);
            }
            """
        )
        self._page.wait_for_function(
            "() => ['flex', 'block'].includes(document.getElementById('selectionModal')?.style.display)",
            timeout=5000,
        )
        self._page.evaluate("document.querySelector('#selectionBody input').focus()")

        self._page.keyboard.press("Enter")
        self._page.wait_for_function(
            "() => ['', 'none'].includes(document.getElementById('selectionModal')?.style.display) && window.__selectionShortcutMessages?.length === 1",
            timeout=5000,
        )

        result = self._page.evaluate(
            """
            () => ({
              display: document.getElementById('selectionModal').style.display,
              messages: window.__selectionShortcutMessages
            })
            """
        )
        self.assertIn(result["display"], ("none", ""))
        self.assertEqual(
            result["messages"],
            [{"type": "select_tasks", "payload": {"indices": [0, 1]}}],
        )

    def test_11ba_primary_button_text_remains_visible_on_hover(self):
        self._goto_ready()
        self._page.evaluate("switchPage('logs')")

        samples = []
        for selector in (
            "#page-logs .log-actions .btn-primary",
            "#selectionConfirmBtn",
        ):
            if selector == "#selectionConfirmBtn":
                self._page.evaluate("showSelectionModal([{title: 'hover contrast'}])")
            locator = self._page.locator(selector)
            locator.wait_for(state="visible")
            before = locator.evaluate(
                "node => ({ background: getComputedStyle(node).backgroundColor, color: getComputedStyle(node).color })"
            )
            locator.hover()
            hovered = locator.evaluate(
                "node => ({ background: getComputedStyle(node).backgroundColor, color: getComputedStyle(node).color })"
            )
            samples.append((before, hovered))

        for before, hovered in samples:
            self.assertEqual(hovered["background"], before["background"], (before, hovered))
            self.assertEqual(hovered["color"], before["color"], (before, hovered))

    def test_11bb_selection_modal_header_fits_and_close_cancels(self):
        self._goto_ready()
        self._page.evaluate(
            """
            () => {
              window.__selectionCloseMessages = [];
              window.sendWS = (type, payload) => window.__selectionCloseMessages.push({ type, payload });
              sendWS = window.sendWS;
              document.documentElement.dataset.language = 'en-US';
              applyStaticLanguage();
              showSelectionModal([{ title: 'first' }, { title: 'second' }]);
            }
            """
        )

        close_button = self._page.locator("#selectionCloseBtn")
        close_button.wait_for(state="visible")
        self.assertEqual(close_button.get_attribute("aria-label"), "Close")
        header_metrics = self._page.locator(".selection-table thead th:first-child").evaluate(
            "node => ({ text: node.textContent.trim(), clientWidth: node.clientWidth, scrollWidth: node.scrollWidth })"
        )
        self.assertEqual(header_metrics["text"], "Select")
        self.assertLessEqual(header_metrics["scrollWidth"], header_metrics["clientWidth"], header_metrics)

        close_button.click()
        self._page.wait_for_function(
            "() => document.getElementById('selectionModal')?.style.display === 'none' && window.__selectionCloseMessages?.length === 1",
            timeout=5000,
        )
        self.assertEqual(
            self._page.evaluate("window.__selectionCloseMessages"),
            [{"type": "select_tasks", "payload": {"indices": None}}],
        )

    def test_11bc_installed_update_modal_ignores_escape_while_normal_modals_close(self):
        self._goto_ready()
        route_pattern = "**/api/update/install"
        pending_routes = []
        self._page.route(route_pattern, lambda route: pending_routes.append(route))

        def release_install_request():
            for route in pending_routes:
                try:
                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body='{"status":"installing","version":"3.6.18"}',
                    )
                except Exception:
                    pass
            self._page.unroute(route_pattern)

        self.addCleanup(release_install_request)
        self._page.evaluate(
            """
            () => {
              const modal = document.getElementById('updateModal');
              const install = document.getElementById('updateInstallBtn');
              modal.style.display = 'flex';
              modal.setAttribute('aria-busy', 'false');
              install.hidden = false;
              install.disabled = false;
              document.getElementById('updateCloseBtn').disabled = false;
              document.getElementById('updateCloseIcon').disabled = false;
            }
            """
        )

        self._page.click("#updateInstallBtn")
        self._page.wait_for_function(
            """
            () => document.getElementById('updateModal').getAttribute('aria-busy') === 'true'
              && document.getElementById('updateStatus').dataset.status === 'installing'
              && document.getElementById('updateCloseBtn').disabled
              && document.getElementById('updateCloseIcon').disabled
            """,
            timeout=5000,
        )
        self._page.keyboard.press("Escape")

        locked_state = self._page.evaluate(
            """
            () => ({
              display: document.getElementById('updateModal').style.display,
              closeDisabled: document.getElementById('updateCloseBtn').disabled,
              iconDisabled: document.getElementById('updateCloseIcon').disabled
            })
            """
        )
        self.assertEqual(locked_state["display"], "flex")
        self.assertTrue(locked_state["closeDisabled"])
        self.assertTrue(locked_state["iconDisabled"])

        self.assertEqual(len(pending_routes), 1)
        pending_routes[0].fulfill(
            status=200,
            content_type="application/json",
            body='{"status":"installing","version":"3.6.18"}',
        )
        pending_routes.clear()
        self._page.wait_for_function(
            "() => document.getElementById('updateNotes').textContent.includes('安装程序') || document.getElementById('updateNotes').textContent.includes('installer')",
            timeout=5000,
        )

        self._page.evaluate(
            """
            () => {
              document.getElementById('updateCloseBtn').disabled = false;
              document.getElementById('updateCloseIcon').disabled = false;
              closeUpdateCheckModal();
              showFileAssociationModal();
            }
            """
        )
        self._page.keyboard.press("Escape")
        self.assertEqual(
            self._page.evaluate("document.getElementById('fileAssociationModal').style.display"),
            "none",
        )

    def test_11c_file_association_modal_esc_and_enter_match_gui(self):
        self._goto_ready()

        esc_result = self._page.evaluate(
            """
            () => {
              showFileAssociationModal();
              return {
                before: document.getElementById('fileAssociationModal').style.display,
                video: document.getElementById('associationVideo').checked,
                image: document.getElementById('associationImage').checked
              };
            }
            """
        )
        self.assertEqual(esc_result["before"], "flex")
        self.assertTrue(esc_result["video"])
        self.assertTrue(esc_result["image"])

        self._page.keyboard.press("Escape")
        self._page.wait_for_function(
            "() => ['', 'none'].includes(document.getElementById('fileAssociationModal')?.style.display)",
            timeout=5000,
        )
        display_after_esc = self._page.evaluate("document.getElementById('fileAssociationModal').style.display")
        self.assertIn(display_after_esc, ("none", ""))

        self._page.evaluate(
            """
            () => {
              window.__associationActions = [];
              window.frontendAction = (action, payload) => window.__associationActions.push({ action, payload });
              frontendAction = window.frontendAction;
              showFileAssociationModal();
              document.getElementById('associationImage').checked = false;
              document.getElementById('associationConfirmBtn').focus();
            }
            """
        )
        self._page.keyboard.press("Enter")
        self._page.wait_for_function(
            "() => ['', 'none'].includes(document.getElementById('fileAssociationModal')?.style.display) && window.__associationActions?.length === 1",
            timeout=5000,
        )

        enter_result = self._page.evaluate(
            """
            () => ({
              display: document.getElementById('fileAssociationModal').style.display,
              actions: window.__associationActions
            })
            """
        )
        self.assertIn(enter_result["display"], ("none", ""))
        self.assertEqual(
            enter_result["actions"],
            [{"action": "register_file_associations", "payload": {"include_video": True, "include_image": False}}],
        )

    def test_11e_dialog_controller_dispose_hides_and_clears_modals_without_actions(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              const actions = [];
              const messages = [];
              window.UcpDialogController.configure({
                getState: () => frontendState,
                t: value => String(value || ''),
                esc,
                escAttr,
                byId: id => document.getElementById(id),
                frontendAction: (action, payload) => actions.push({ action, payload }),
                sendWS: (type, payload) => messages.push({ type, payload }),
                appendUiLog: () => {}
              });
              window.UcpDialogController.showSelection([{ title: 'one' }, { title: 'two' }]);
              window.UcpDialogController.showAssociation();
              document.getElementById('dirModal').style.display = 'flex';
              window.UcpDialogController.dispose();
              window.UcpDialogController.dispose();
              return {
                actions,
                messages,
                selectionDisplay: document.getElementById('selectionModal').style.display,
                associationDisplay: document.getElementById('fileAssociationModal').style.display,
                directoryDisplay: document.getElementById('dirModal').style.display,
                selectionHtml: document.getElementById('selectionBody').innerHTML
              };
            }
            """
        )

        self.assertEqual(result["actions"], [])
        self.assertEqual(result["messages"], [])
        self.assertEqual(result["selectionDisplay"], "none")
        self.assertEqual(result["associationDisplay"], "none")
        self.assertEqual(result["directoryDisplay"], "none")
        self.assertEqual(result["selectionHtml"], "")

    def test_11eb_dialog_dispose_ignores_late_directory_response_and_cancels_focus(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              let resolveFetch;
              let focusCalls = 0;
              const originalFetch = window.fetch;
              const input = document.getElementById('dirInput');
              const originalFocus = input.focus.bind(input);
              input.focus = () => { focusCalls += 1; };
              window.fetch = () => new Promise(resolve => { resolveFetch = resolve; });
              const actions = [];
              const patches = [];
              window.UcpDialogController.configure({
                getState: () => ({ settings_snapshot: { '\u57fa\u7840\u8bbe\u7f6e': { download_directory: 'D:/start' } } }),
                t: value => String(value || ''),
                esc,
                escAttr,
                byId: id => document.getElementById(id),
                frontendAction: (action, payload) => actions.push({ action, payload }),
                sendWS: (type, payload) => actions.push({ type, payload }),
                appendUiLog: value => actions.push({ log: value }),
                patchSetting: (group, key, value) => patches.push({ group, key, value })
              });
              const pending = window.UcpDialogController.showDirectory();
              const statusAtDispose = document.getElementById('dirStatus').textContent;
              const inputAtDispose = input.value;
              window.UcpDialogController.dispose();
              await new Promise(resolve => requestAnimationFrame(resolve));
              resolveFetch({
                ok: true,
                status: 200,
                json: () => Promise.resolve({ current: 'D:/late', parent: 'D:/', drives: [], subdirs: [{ name: 'late', path: 'D:/late' }] })
              });
              let pendingError = '';
              await pending.catch(error => { pendingError = String(error && error.message || error); });
              const observed = {
                actions,
                patches,
                pendingError,
                focusCalls,
                display: document.getElementById('dirModal').style.display,
                inputValue: input.value,
                inputAtDispose,
                status: document.getElementById('dirStatus').textContent,
                statusAtDispose,
                listText: document.getElementById('dirList').textContent.trim()
              };
              input.focus = originalFocus;
              window.fetch = originalFetch;
              return observed;
            }
            """
        )

        self.assertEqual(result["actions"], [])
        self.assertEqual(result["patches"], [])
        self.assertEqual(result["pendingError"], "")
        self.assertEqual(result["focusCalls"], 0)
        self.assertEqual(result["display"], "none")
        self.assertEqual(result["inputValue"], result["inputAtDispose"])
        self.assertEqual(result["status"], result["statusAtDispose"])
        self.assertEqual(result["listText"], "")

    def test_11ebb_dialog_directory_listeners_are_owned_and_disposed(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              const originalFetch = window.fetch;
              const input = document.getElementById('dirInput');
              const list = document.getElementById('dirList');
              const errors = [];
              const rejections = [];
              let fetchCalls = 0;
              const onError = event => { errors.push(String(event.error || event.message || 'error')); event.preventDefault(); };
              const onRejection = event => { rejections.push(String(event.reason || 'rejection')); event.preventDefault(); };
              const nextTask = () => new Promise(resolve => {
                const channel = new MessageChannel();
                channel.port1.onmessage = () => { channel.port1.close(); channel.port2.close(); resolve(); };
                channel.port2.postMessage(null);
              });
              const configure = () => window.UcpDialogController.configure({
                getState: () => ({ settings_snapshot: {} }),
                t: value => String(value || ''),
                esc,
                escAttr,
                byId: id => document.getElementById(id),
                frontendAction: () => {},
                sendWS: () => {},
                appendUiLog: () => {}
              });
              window.addEventListener('error', onError);
              window.addEventListener('unhandledrejection', onRejection);
              window.fetch = () => {
                fetchCalls += 1;
                return Promise.resolve({
                  ok: true,
                  status: 200,
                  json: () => Promise.resolve({ current: 'D:/active', parent: 'D:/', drives: [], subdirs: [] })
                });
              };
              try {
                configure();
                window.UcpDialogController.installDirectoryHandlers();
                window.UcpDialogController.installDirectoryHandlers();
                configure();
                window.UcpDialogController.installDirectoryHandlers();
                window.UcpDialogController.installDirectoryHandlers();

                input.value = 'D:/active';
                input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
                await nextTask();
                const callsWhileActive = fetchCalls;

                window.UcpDialogController.dispose();
                window.UcpDialogController.dispose();
                const button = document.createElement('button');
                button.dataset.dirPath = 'D:/disposed';
                list.replaceChildren(button);
                input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
                button.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                button.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
                await nextTask();

                return { callsWhileActive, callsAfterDispose: fetchCalls, errors, rejections };
              } finally {
                window.UcpDialogController.dispose();
                window.fetch = originalFetch;
                window.removeEventListener('error', onError);
                window.removeEventListener('unhandledrejection', onRejection);
                if (typeof configureDialogControllerHelpers === 'function') configureDialogControllerHelpers();
              }
            }
            """
        )

        self.assertEqual(result["callsWhileActive"], 1)
        self.assertEqual(result["callsAfterDispose"], 1)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["rejections"], [])

    def test_11ebc_stale_focus_callback_cannot_clear_current_run_handle(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              const originalRequestAnimationFrame = window.requestAnimationFrame;
              const originalCancelAnimationFrame = window.cancelAnimationFrame;
              const confirm = document.getElementById('associationConfirmBtn');
              const originalFocus = confirm.focus.bind(confirm);
              const frames = [];
              const cancelled = [];
              let focusCalls = 0;
              const configure = () => window.UcpDialogController.configure({
                getState: () => ({ settings_snapshot: {} }),
                t: value => String(value || ''),
                esc,
                escAttr,
                byId: id => document.getElementById(id),
                frontendAction: () => {},
                sendWS: () => {},
                appendUiLog: () => {}
              });
              window.requestAnimationFrame = callback => {
                const frame = { id: frames.length + 1, callback };
                frames.push(frame);
                return frame.id;
              };
              window.cancelAnimationFrame = id => { cancelled.push(id); };
              confirm.focus = () => { focusCalls += 1; };
              try {
                configure();
                window.UcpDialogController.showAssociation();
                const frameA = frames.at(-1);
                configure();
                window.UcpDialogController.showAssociation();
                const frameB = frames.at(-1);

                frameA.callback();
                window.UcpDialogController.dispose();
                window.UcpDialogController.dispose();
                frameB.callback();

                return {
                  staleFrameCancelled: cancelled.includes(frameA.id),
                  currentFrameCancelled: cancelled.includes(frameB.id),
                  focusCalls
                };
              } finally {
                window.UcpDialogController.dispose();
                window.requestAnimationFrame = originalRequestAnimationFrame;
                window.cancelAnimationFrame = originalCancelAnimationFrame;
                confirm.focus = originalFocus;
                if (typeof configureDialogControllerHelpers === 'function') configureDialogControllerHelpers();
              }
            }
            """
        )

        self.assertTrue(result["staleFrameCancelled"])
        self.assertTrue(result["currentFrameCancelled"])
        self.assertEqual(result["focusCalls"], 0)

    def test_11ec_dialog_reconfigure_ignores_old_json_continuation(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              let resolveOldJson;
              const originalFetch = window.fetch;
              window.fetch = url => {
                const text = String(url);
                if (text.includes('old')) {
                  return Promise.resolve({
                    ok: true,
                    status: 200,
                    json: () => new Promise(resolve => { resolveOldJson = resolve; })
                  });
                }
                return Promise.resolve({
                  ok: true,
                  status: 200,
                  json: () => Promise.resolve({ current: 'D:/new', parent: 'D:/', drives: [], subdirs: [{ name: 'new', path: 'D:/new' }] })
                });
              };
              const configure = () => window.UcpDialogController.configure({
                getState: () => ({ settings_snapshot: {} }),
                t: value => String(value || ''),
                esc,
                escAttr,
                byId: id => document.getElementById(id),
                frontendAction: () => {},
                sendWS: () => {},
                appendUiLog: () => {},
                patchSetting: () => {}
              });
              configure();
              const oldPending = window.UcpDialogController.loadDirectory('D:/old');
              await Promise.resolve();
              configure();
              await window.UcpDialogController.loadDirectory('D:/new');
              resolveOldJson({ current: 'D:/old', parent: 'D:/', drives: [], subdirs: [{ name: 'old', path: 'D:/old' }] });
              await oldPending;
              const observed = {
                inputValue: document.getElementById('dirInput').value,
                listText: document.getElementById('dirList').textContent.trim(),
                status: document.getElementById('dirStatus').textContent
              };
              window.UcpDialogController.dispose();
              window.fetch = originalFetch;
              return observed;
            }
            """
        )

        self.assertEqual(result["inputValue"], "D:/new")
        self.assertEqual(result["listText"], "new")
        self.assertIn("\u5355\u51fb\u9009\u62e9", result["status"])

    def test_11ed_newer_directory_load_wins_when_old_response_arrives_late(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              let resolveOld;
              const originalFetch = window.fetch;
              window.fetch = url => String(url).includes('old')
                ? new Promise(resolve => { resolveOld = resolve; })
                : Promise.resolve({
                    ok: true,
                    status: 200,
                    json: () => Promise.resolve({ current: 'D:/newest', parent: 'D:/', drives: [], subdirs: [{ name: 'newest', path: 'D:/newest' }] })
                  });
              window.UcpDialogController.configure({
                getState: () => ({ settings_snapshot: {} }),
                t: value => String(value || ''),
                esc,
                escAttr,
                byId: id => document.getElementById(id),
                frontendAction: () => {},
                sendWS: () => {},
                appendUiLog: () => {},
                patchSetting: () => {}
              });
              const oldPending = window.UcpDialogController.loadDirectory('D:/old');
              await window.UcpDialogController.loadDirectory('D:/newest');
              resolveOld({
                ok: true,
                status: 200,
                json: () => Promise.resolve({ current: 'D:/old', parent: 'D:/', drives: [], subdirs: [{ name: 'old', path: 'D:/old' }] })
              });
              await oldPending;
              const observed = {
                inputValue: document.getElementById('dirInput').value,
                listText: document.getElementById('dirList').textContent.trim()
              };
              window.UcpDialogController.dispose();
              window.fetch = originalFetch;
              return observed;
            }
            """
        )

        self.assertEqual(result["inputValue"], "D:/newest")
        self.assertEqual(result["listText"], "newest")

    def test_14_keyboard_arrow_navigation(self):
        """方向键应在可见队列行之间切换。"""
        self._goto_ready()
        # 注入测试数据
        self._page.evaluate("""
            window.__isolateFrontendStateForTest();
            switchPage('queue');
            frontendState.queue_items = [
                {id: 'a', title: 'Item A', progress: 0, status: 'done'},
                {id: 'b', title: 'Item B', progress: 0, status: 'done'},
                {id: 'c', title: 'Item C', progress: 0, status: 'done'},
            ];
            selectedVideoId = null;
            window.UcpListPages.renderQueue();
            document.body.focus();
        """)
        self._page.wait_for_function(
            "() => document.querySelectorAll('#queueBody tr[data-id]').length === 3",
            timeout=5000,
        )
        # 第一次按 ArrowDown → 选中 a
        self._page.keyboard.press("ArrowDown")
        self._page.wait_for_function("() => selectedVideoId === 'a'", timeout=5000)
        sel = self._page.evaluate("selectedVideoId")
        self.assertEqual(sel, "a")
        # 再按 ArrowDown → 选中 b
        self._page.keyboard.press("ArrowDown")
        self._page.wait_for_function("() => selectedVideoId === 'b'", timeout=5000)
        sel = self._page.evaluate("selectedVideoId")
        self.assertEqual(sel, "b")

    def test_15_delete_key_removes(self):
        """Delete 键应触发删除。"""
        self._goto_ready()
        self._page.evaluate("""
            window.__isolateFrontendStateForTest();
            window._deletedIds = [];
            frontendState.queue_items = [{id: 'x1', title: 'to delete', progress: 0, status: 'done'}];
            window.UcpListPages.renderQueue();
            selectedVideoId = 'x1';
            updateSelection(null, 'x1');
            window.UcpPlaybackController.configure({
                ...playbackControllerDependencies(),
                frontendAction: (action, payload) => {
                    if (action === 'delete_item') window._deletedIds.push(payload.id);
                }
            });
        """)
        # 焦点不在输入框
        self._page.wait_for_selector(
            "#page-queue.active #queueBody tr[data-id='x1'].selected",
            state="visible",
            timeout=5000,
        )
        self._page.evaluate("document.body.focus()")
        self._page.keyboard.press("Delete")
        self._page.wait_for_function("() => window._deletedIds?.length === 1", timeout=5000)
        deleted = self._page.evaluate("window._deletedIds")
        self.assertEqual(deleted, ["x1"])

    def test_15b_hidden_page_selection_cannot_trigger_delete(self):
        self._goto_ready()
        self._page.evaluate(
            """
            () => {
              window.__isolateFrontendStateForTest();
              window._deletedIds = [];
              frontendState.queue_items = [{id: 'hidden-queue', title: 'Hidden queue item'}];
              window.UcpListPages.renderQueue();
              selectedVideoId = 'hidden-queue';
              updateSelection(null, 'hidden-queue');
              window.UcpPlaybackController.configure({
                ...playbackControllerDependencies(),
                frontendAction: (action, payload) => {
                  if (action === 'delete_item') window._deletedIds.push(payload.id);
                }
              });
              switchPage('logs');
              document.body.focus();
            }
            """
        )

        self._page.keyboard.press("Delete")

        deleted = self._page.evaluate("window._deletedIds")
        self.assertEqual(deleted, [])

    def test_15c_arrow_navigation_is_owned_by_the_visible_task_page(self):
        self._goto_ready()
        self._page.evaluate(
            """
            () => {
              window.__isolateFrontendStateForTest();
              frontendState.queue_items = [
                {id: 'queue-a', title: 'Queue A'},
                {id: 'queue-b', title: 'Queue B'},
              ];
              frontendState.failed_items = [
                {id: 'failed-a', title: 'Failed A', status: 'failed'},
                {id: 'failed-b', title: 'Failed B', status: 'failed'},
              ];
              selectedVideoId = 'queue-a';
              selected.failed = 'failed-a';
              window.UcpListPages.renderQueue();
              window.UcpListPages.renderFailed();
              switchPage('failed');
              document.body.focus();
            }
            """
        )
        self._page.wait_for_function(
            "() => document.querySelectorAll('#failedBody tr[data-id]').length === 2",
            timeout=5000,
        )
        self._page.evaluate(
            """
            () => {
              window.Worker = class DeferredListWorker {
                postMessage() {}
                terminate() {}
              };
              configureListPagesHelpers();
              selected.failed = 'failed-a';
            }
            """
        )

        self._page.keyboard.press("ArrowDown")
        self._page.wait_for_function("() => selected.failed === 'failed-b'", timeout=5000)

        result = self._page.evaluate(
            """
            () => ({
              failedSelection: selected.failed,
              queueSelection: selectedVideoId,
              selectedRow: document.querySelector('#failedBody tr.selected')?.dataset.id || '',
            })
            """
        )
        self.assertEqual(result["failedSelection"], "failed-b")
        self.assertEqual(result["queueSelection"], "queue-a")
        self.assertEqual(result["selectedRow"], "failed-b")
