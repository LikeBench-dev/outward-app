# Windows client freeze during background log refresh

On 2026-11-07, the installed `C:\OutwardApp\Outward App.exe` was inspected while Windows reported its GUI as not responding. The GUI child PID was 16504, started at 07:54 Moscow time. Python was 3.12.14. Repeated `py-spy dump --pid 16504 --native` captures found the same blocked stacks; the process was not terminated to collect them. The full capture is local and ignored at `build/hang-diagnostics/outward-hang-native.txt`.

The main thread was in `_background_result` → `_system_log_received` → `_render_log_text` → `QTextEdit::setHtml`. Native frames showed the document/scrollbar signals waiting in `QBasicMutex::lockInternal` / `WaitOnAddress`. A background QThread was simultaneously inside `QObject::~QObject` → `Sbk_GetPyOverride` → `PyGILState_Ensure`. Session, ping and traffic workers were idle.

Together, these stacks identify a Qt signal-mutex / Python GIL lock inversion during destruction of a Python-backed worker QObject while the GUI rendered the completed log result. The old system-log timer repeatedly created a QThread, moved a Python QObject into it and scheduled worker deletion there.

## Change

- Browser, installer and log functions run in a bounded Python thread pool. Workers do not create/delete Qt objects or emit completion signals. A GUI timer reads completed futures, removes the job key and calls the result handler on the GUI thread. Duplicate outstanding keys are ignored; failed jobs can be retried and errors remain sanitized.
- Update check/download workers subclass QThread directly. Their QObject wrappers retain GUI affinity and are deleted in the GUI thread after the native thread finishes.
- App shutdown continues collecting results until background jobs and update threads finish, then closes the executor before quitting.

## Regression checks

`tests/test_ui.py` checks asynchronous execution, GUI-thread delivery, deduplication, retry after a sanitized error, update check/download delivery and waiting for outstanding jobs during shutdown.

A separate process using the native Windows Qt plugin renders 1000 changing, multiline background log results while completing and deleting 100 update threads. The process uses synthetic data and mocked network/service boundaries, and has a 60-second timeout so a deadlock cannot stall the suite. The normal UI suite also checks native window layout. These accelerated tests exercise the captured failure path; they do not establish indefinite unattended runtime or real VPN stability.

Validation on 2026-11-07: all 112 tests passed in 43.606 seconds; `compileall` passed. The changing-log native stress test passed, and a synthetic native log render was visually inspected. `build-installer.ps1 -NoVersionBump` produced the local 0.1.6 installer without committing, publishing or installing it. Both built executables exited with code 0 for `--check-runtime`. Existing ignore rules cover `build/`, `dist/`, `installer-output/` and Python caches; no additional ignore rules were needed.

## Tray Exit leaves an idle process

Later on 2026-11-07, after the user selected Exit from the tray, the installed GUI child PID 28480 remained alive alongside its onefile parent PID 32184. Repeated native `py-spy` captures found only the Python main thread, idle in `QCoreApplication::exec` / `MsgWaitForMultipleObjectsEx`. Connection and background worker threads had already ended. This was a separate event-loop lifecycle problem, rather than the earlier worker deadlock.

Closing a window already hidden in the tray does not cause Qt's implicit last-window shutdown. The final `_close_ready` branch now explicitly calls `QApplication.quit()` after accepting the close event and hiding the tray icon. Connection cleanup and the drain of background jobs/update threads still finish first.

`test_tray_exit_terminates_event_loop_after_hidden_window_cleanup` runs a native Windows Qt event loop in a subprocess with synthetic storage and a pending background job. It closes the window into the tray, requests Exit, releases the job, and requires the event loop and process to terminate normally. The test failed before the fix because Qt's event loop survived Exit; it passes after the fix. All 44 UI tests passed, including native background-log stress and tray-exit checks.

The syntax check and `git diff --check` passed. The local 0.1.6 installer was rebuilt with `-NoVersionBump`; both packaged executables passed `--check-runtime` with exit code 0. The installer has not been installed or published. Existing ignore rules cover the build log, binaries, installer and Python caches.
