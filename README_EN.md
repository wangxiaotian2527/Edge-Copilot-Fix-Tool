# Edge Copilot Repair Tool

[简体中文](./README.md) | **English**

Diagnose and repair local Microsoft Edge settings that affect the visibility of the Copilot entry point. The tool provides an interactive Chinese menu and a full command-line interface for manual use or automation.

**Single-file application: download [patch_edge_copilot.py](./patch_edge_copilot.py).** Seed-file processing is built in; no other Python files from this project are required.

The script handles both legacy JSON settings and country metadata in the newer `VariationsSeedV2` file. It has restored the Copilot entry point on Windows with Edge **153.0.4234.32**. Results may differ across browser versions, accounts, and network environments.

## Contents

- [Features](#features)
- [Requirements and installation](#requirements-and-installation)
- [Quick start](#quick-start)
- [Interactive menu](#interactive-menu)
- [Command-line usage](#command-line-usage)
- [Argument reference](#argument-reference)
- [Automation](#automation)
- [Profile locations and scope of changes](#profile-locations-and-scope-of-changes)
- [Closing and reopening Edge](#closing-and-reopening-edge)
- [Backups and recovery](#backups-and-recovery)
- [How it works and limitations](#how-it-works-and-limitations)
- [Troubleshooting](#troubleshooting)
- [Tests](#tests)
- [Reporting issues](#reporting-issues)
- [References](#references)

## Features

- **Interactive menu:** launch without arguments and select repair, preview, diagnostics, or other actions by number.
- **Command-line mode:** supplying arguments runs the requested operation without menu prompts.
- **Support for newer seed files:** synchronize existing country fields in `VariationsSeedV2` while preserving experiment data, signatures, and other fields.
- **Multiple channels and profiles:** select Stable, Beta, Dev, Canary, or a custom user data directory.
- **Process checks:** confirm Edge has exited before writing; inspect remaining processes by PID and type.
- **Automatic backups:** preserve the original bytes before atomic replacement and read-back verification.
- **Optional reopening:** open the selected Edge profile after a successful repair.
- **Repeatable operation:** files already matching the target settings are not rewritten or backed up again.

## Requirements and installation

| Component | Requirements and notes |
| --- | --- |
| Python | 3.8 or later; verified with Python 3.8 |
| Microsoft Edge | Installed and launched at least once to create its user configuration |
| Windows | Verified in practice; includes process-exit checks and read-only registry diagnostics |
| macOS / Linux | Path discovery and basic handling are implemented, but have not received equivalent practical validation |
| `psutil` | Used to inspect and close browser processes |
| Zstandard support | Installing `zstandard` is recommended; an existing Zstandard shared library discoverable by the script can also be used |

Download the script and [requirements.txt](./requirements.txt), then open PowerShell or a terminal in their directory and install the dependencies:

```powershell
python --version
python -m pip install -r requirements.txt
```

If you downloaded only the standalone script, you can install the dependencies directly:

```powershell
python -m pip install "psutil>=5.8.0" "zstandard>=0.23.0"
```

If your system uses `python3` or `py`, replace `python` accordingly. Use the same interpreter to install dependencies and run the script.

“Single-file” means that no additional project-local `.py` files are needed. Python and the dependencies above are still required. The script does not install dependencies automatically.

Run it as the same operating-system user who normally uses Edge. Administrator privileges are usually unnecessary; running under a different account may target the wrong profile directory.

## Quick start

```powershell
python patch_edge_copilot.py
```

1. Save any unfinished work in Edge tabs.
2. The menu defaults to **Stable / Default**. Select `5` first if you use a different channel or profile.
3. Optionally select `2` to preview the proposed changes.
4. Select `1` to repair Copilot.
5. At the prompt asking whether to reopen Edge after a successful repair, press Enter or type `y` to reopen it, or type `n` to leave it closed.
6. Check the Copilot entry point in Edge. Launch the browser manually if you chose not to reopen it automatically.

Opening the menu does not change any settings. Writes are attempted only when you select the repair action or pass `--apply` on the command line.

## Interactive menu

The program's menu, prompts, and most diagnostic messages are currently in Chinese. The following is an English translation of the menu for reference; this README does not add an English interface to the program.

```text
========== Edge Copilot Repair Tool ==========
Current target: Stable / Default
1. Repair Copilot (close Edge automatically)
2. Preview repair changes
3. Read-only diagnostics
4. List Edge processes
5. Change browser channel / profile directory
0. Exit
Select an action [0-5]:
```

| Option | Behavior |
| --- | --- |
| `1` | Apply JSON and seed-country repairs, close Edge if necessary, and ask whether to reopen it after success |
| `2` | Preview changes, including seed repair, without closing the browser or writing files |
| `3` | Inspect settings without changing them; on Windows, also check relevant registry policies and proxy configuration status |
| `4` | List active Edge processes belonging to the current user to help identify background processes |
| `5` | Choose a channel or custom User Data directory, then specify a profile directory name |
| `0` | Exit |

Press Enter after an operation to return to the menu. Your target selection lasts only for the current run; it is not saved in an extra settings file.

When choosing a profile directory:

- Press Enter to use `Default`.
- Enter a directory name such as `Profile 1` to process only that profile's `Preferences`.
- Enter `*` to process all existing regular profiles in the selected user data directory.

Use the **directory name on disk**, not the account nickname shown in Edge. The menu does not enable `--force-close` by default.

## Command-line usage

Most examples below target the Stable channel's `Default` profile. **Supplying arguments bypasses the menu.** If you specify only a path, channel, or other options without selecting an action, the script performs read-only diagnostics.

### Show help or run diagnostics

```powershell
python patch_edge_copilot.py --help
python patch_edge_copilot.py --diagnose --profile Default
python patch_edge_copilot.py --list-processes
```

### Preview a full repair

```powershell
python patch_edge_copilot.py --dry-run --patch-seed --profile Default
```

`--dry-run` does not modify files or close the browser. Include `--patch-seed` to include country metadata in the newer standalone seed file in the repair plan.

### Repair without reopening Edge

```powershell
python patch_edge_copilot.py --apply --patch-seed --profile Default --close-edge
```

Command-line mode does not reopen the browser by default. You can also specify `--no-restart-edge` explicitly.

If you have already closed all Edge windows and background processes manually, omit `--close-edge`:

```powershell
python patch_edge_copilot.py --apply --patch-seed --profile Default
```

### Reopen Edge after a successful repair

```powershell
python patch_edge_copilot.py --apply --patch-seed --profile Default --close-edge --restart-edge
```

### Select another channel or multiple profiles

Repair `Profile 1` in the Beta channel:

```powershell
python patch_edge_copilot.py --apply --patch-seed --channel beta --profile "Profile 1" --close-edge --restart-edge
```

Process two profiles in the same channel:

```powershell
python patch_edge_copilot.py --apply --patch-seed --profile Default --profile "Profile 1" --close-edge
```

Omitting `--profile` processes the existing regular `Default` and `Profile *` directories under the target user data directory. By contrast, the menu initially selects only `Default`.

Preview changes across all detected channels:

```powershell
python patch_edge_copilot.py --dry-run --patch-seed --channel all
```

### Use a custom user data directory

```powershell
python patch_edge_copilot.py --apply --patch-seed --user-data-dir "D:\EdgeData\User Data" --profile Default --close-edge
```

The directory must contain `Local State`. Do not point directly to `Default` or `Profile 1`.

To reopen a browser installed in a nonstandard location, provide its executable path:

```powershell
python patch_edge_copilot.py --apply --patch-seed --user-data-dir "D:\EdgeData\User Data" --profile Default --close-edge --restart-edge --edge-exe "D:\Apps\Edge\Application\msedge.exe"
```

### Repair only legacy JSON settings

```powershell
python patch_edge_copilot.py --apply --profile Default --close-edge
```

Without `--patch-seed`, the standalone seed file is not modified. On versions that read country metadata from `VariationsSeedV2`, JSON changes alone may not restore the entry point.

## Argument reference

| Argument | Purpose | Default / notes |
| --- | --- | --- |
| `-h`, `--help` | Show help and exit | Does not repair anything |
| `--diagnose` | Read-only diagnostics | Default when only non-action options are supplied |
| `--dry-run` | Preview proposed changes | Does not write files or close the browser |
| `--apply` | Back up and apply the patch | Explicitly enables writes |
| `--list-processes` | List the current user's active Edge processes | Does not modify files; not filtered by channel or profile |
| `--channel` | Select a channel | `stable`; also accepts `beta`, `dev`, `canary`, or `all` |
| `--user-data-dir` | Specify the user data root | Takes precedence over channel-based directory discovery |
| `--profile` | Specify a profile directory name | Repeatable; the CLI processes all regular profiles if omitted |
| `--country` | Set the target country cache value | `US`; accepts two English letters and converts them to uppercase |
| `--patch-seed` | Synchronize country metadata in the standalone seed | Off by default in the CLI; enabled for menu repair and preview |
| `--close-edge` | Close Edge before writing | Requires `--apply` |
| `--force-close` | Force termination if normal shutdown fails | Requires both `--apply` and `--close-edge` |
| `--restart-edge` | Open the target Edge window after success | Requires `--apply` |
| `--no-restart-edge` | Leave Edge closed | Default CLI behavior |
| `--edge-exe` | Specify the executable used to reopen Edge | Automatically locates the selected channel by default |

Combination rules:

- `--diagnose`, `--dry-run`, `--apply`, and `--list-processes` are mutually exclusive.
- `--restart-edge` and `--no-restart-edge` are mutually exclusive.
- `--close-edge`, `--force-close`, and `--restart-edge` cannot be used with read-only actions.
- Without a custom User Data directory, `--edge-exe` cannot be combined with `--channel all`.
- `--country` changes only local cache values, not your actual network location or account region.

## Automation

For batch files, PowerShell scripts, and scheduled tasks, use explicit command-line arguments instead of feeding numbers into the menu.

### PowerShell example

Replace these paths with your actual locations:

```powershell
$pythonExe = "C:\Python\python.exe"
$scriptPath = "D:\Tools\patch_edge_copilot.py"

& $pythonExe $scriptPath --apply --patch-seed --profile Default --close-edge --no-restart-edge
$resultCode = $LASTEXITCODE

if ($resultCode -ne 0) {
    Write-Error "Edge Copilot configuration failed. Exit code: $resultCode"
}
exit $resultCode
```

Replace `--no-restart-edge` with `--restart-edge` if you want the browser to open afterward.

### Windows Task Scheduler

An action can use the following values, adjusted for your installation:

| Field | Example |
| --- | --- |
| Program/script | `C:\Python\python.exe` |
| Add arguments | `"D:\Tools\patch_edge_copilot.py" --apply --patch-seed --profile Default --close-edge --no-restart-edge` |
| Start in | `D:\Tools` |

Use the account that normally runs Edge, and execute in that user's interactive login session. Window closing and visibility checks depend on the session; background execution across sessions has not been validated. If the task uses `--close-edge`, make sure there is no unsaved browser work when it runs.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | The operation completed, or no settings needed to change |
| `1` | A configuration read, process operation, write, or browser launch failed |
| `2` | Invalid command-line arguments |
| `130` | The interactive menu was interrupted with Ctrl+C |

Exit code `0` means the script completed; it does not guarantee that the Copilot service is available. The menu's exit code describes the menu session, not the result of every repair performed within it. Use argument-based execution for automation.

## Profile locations and scope of changes

### Find your profile

Open `edge://version` in Edge and look for **Profile path**. For example:

```text
C:\Users\<username>\AppData\Local\Microsoft\Edge\User Data\Profile 1
```

Use:

- The parent `User Data` directory for `--user-data-dir`.
- The final directory name, `Profile 1`, for `--profile`.

Default Windows data locations:

| Channel | User data directory |
| --- | --- |
| Stable | `%LOCALAPPDATA%\Microsoft\Edge\User Data` |
| Beta | `%LOCALAPPDATA%\Microsoft\Edge Beta\User Data` |
| Dev | `%LOCALAPPDATA%\Microsoft\Edge Dev\User Data` |
| Canary | `%LOCALAPPDATA%\Microsoft\Edge SxS\User Data` |

On macOS and Linux, the script uses platform-specific paths. You can also specify `--user-data-dir` directly.

### What is modified

| File | Target fields / behavior |
| --- | --- |
| `Local State` | Set `variations_country`; synchronize the country in an existing, valid `variations_permanent_consistency_country` value while preserving its version |
| Selected profile's `Preferences` | Set `browser.chat_ip_eligibility_status=true` and `browser.show_discover_toolbar_button=true` |
| `VariationsSeedV2` | With `--patch-seed` only, synchronize existing, recognized country fields 6 and 7 |

**`--profile` limits only which `Preferences` files are selected.** `Local State` and `VariationsSeedV2` are shared by the entire user data directory, so country changes also affect its other profiles.

Other configuration fields are preserved. The script does not change organization policies, page-reading permissions, `VariationsSafeSeedV2`, or safe-seed metadata in `Local State`. It does not invent missing or unrecognized country values or create new Edge profiles.

## Closing and reopening Edge

### Closing behavior

With `--close-edge`, the script first requests that the current user's Edge windows close, then repeatedly checks whether the processes have exited.

On Windows, if only background instances explicitly started with `--no-startup-window` remain, and repeated checks find no visible windows or page renderer processes, the script terminates those background instances and rereads the configuration from disk. WebView2 and the Edge updater are not included in the browser processes to close.

If page renderers, extension pages, headless automation, or unknown process types remain, the script does not automatically force termination. Instead, it lists their PIDs and process types. Check these in Task Manager's **Details** tab.

**Shutdown applies to all Edge browser processes owned by the current user, including other channels; it is not limited by `--profile`.** To avoid having the script close browsers, fully exit Edge manually and omit `--close-edge`.

If you have saved your work and need to force shutdown:

```powershell
python patch_edge_copilot.py --apply --patch-seed --profile Default --close-edge --force-close
```

Forced termination may lose unsaved page content and does not guarantee that normal shutdown writes complete.

### Reopening behavior

- Menu repair asks whether to reopen Edge and defaults to yes. Command-line mode defaults to leaving it closed.
- Reopening uses the selected channel, user data directory, and profile. Specifying multiple distinct `--profile` values sends a separate window-opening request for each.
- If settings already match the target, `--restart-edge` still requests a window even though no repair is needed.
- Repair failures do not automatically reopen Edge. If only the browser launch fails, configuration changes may already have completed; the output explains this.
- Opening a window does not guarantee restoration of all previous tabs. Session restoration depends on Edge's own settings.
- The script reports that a launch request was sent. It does not automatically verify that a window appeared or that Copilot responded.

## Backups and recovery

Each file that needs modification gets its own backup beside the original, with a name such as:

```text
Local State.copilot-backup-<date-time>-<nanoseconds>.bak
Preferences.copilot-backup-<date-time>-<nanoseconds>.bak
VariationsSeedV2.copilot-backup-<date-time>-<nanoseconds>.bak
```

Backups preserve the original bytes and do not overwrite earlier backups. No backup is created for an unchanged file. The terminal prints the full path of each backup.

To restore:

1. Fully exit Edge, including its background processes.
2. Find the backups from the run you want to undo.
3. Copy each backup over its original file in the same directory, using the original filename.
4. If that run modified several files, restore the corresponding set of backups before reopening Edge.

PowerShell example; substitute the actual backup path before running:

```powershell
$backupPath = "D:\EdgeData\User Data\Local State.copilot-backup-<date-time>-<nanoseconds>.bak"
$targetPath = "D:\EdgeData\User Data\Local State"
Copy-Item -LiteralPath $backupPath -Destination $targetPath -Force
```

Restoring an older complete configuration file also overwrites settings changed in that file since the backup was taken. There is currently no dedicated restore menu.

Writes use temporary files in the same directory, concurrent-change checks, atomic replacement, and read-back verification. However, updates to multiple files are not one transaction. If a later step fails, earlier changes and their backups remain; use the output to decide whether to retry or restore. Keep browser configurations and backups local rather than attaching them publicly to bug reports.

## How it works and limitations

Legacy fixes typically adjusted only the country cache in `Local State` and button-related settings in `Preferences`. Newer Chromium seed storage also keeps country metadata in `VariationsSeedV2`. When that storage mode is active, editing JSON does not directly change the country values in the seed file. [Chromium seed reader/writer implementation](https://github.com/chromium/chromium/blob/2bc48d1e3a591d641005e9bc640adfd6c77c517f/components/variations/seed_reader_writer.cc)

`VariationsSeedV2` contains a Zstandard-compressed protobuf. With `--patch-seed`, the script replaces only existing, valid two-letter country values. All other protobuf bytes, including experiment data and signatures, are preserved; signatures are not regenerated or forged. [StoredSeedInfo definition](https://github.com/chromium/chromium/blob/2bc48d1e3a591d641005e9bc640adfd6c77c517f/components/variations/proto/stored_seed_info.proto)

This tool edits local configuration and is not an official Microsoft recovery interface. It cannot guarantee removal of server-side regional, account, or organizational restrictions, or prevent the browser from rewriting its settings later. If the entry point returns but the service remains unavailable, check the network, account, and effective browser policies.

## Troubleshooting

### Automation opens a menu instead of applying the repair

Launching without arguments enters menu mode. Specify `--apply` and the other required options for automation; see [Automation](#automation).

### Missing `psutil` or Zstandard support

Install dependencies with the same interpreter used to run the script:

```powershell
python -m pip install -r requirements.txt
```

If the error persists, check whether installation and execution are using different Python installations, virtual environments, or Conda environments.

### User data directory or Preferences not found

Launch the relevant Edge channel at least once, then confirm its actual profile path at `edge://version`. Point `--user-data-dir` to the root containing `Local State`, and use a child directory name for `--profile`.

### Edge windows are closed, but processes are still reported

Startup boost or background services may continue after the windows close. Run:

```powershell
python patch_edge_copilot.py --list-processes
```

Check the listed PIDs in Task Manager's **Details** tab. If needed, disable startup boost and background operation in Edge settings. Eligible background instances with no pages are handled automatically by `--close-edge`; others require manual handling or explicit `--force-close` after saving your work.

### Process ownership cannot be confirmed, or access is denied

Make sure Edge and the script run under the same system account. Avoid running one with elevated privileges and the other without them. Do not delete or recreate the user data directory to work around this error.

### VariationsSeedV2 was not found

The script skips standalone seed repair and continues checking existing JSON files. Storage can differ by version and run history; do not create an empty seed file manually.

### Unrecognized seed format or corrupted file

Do not manually truncate or empty the seed file. When `--patch-seed` is enabled, failure to read the seed prevents writes for that run. Report the Edge version and error text. You can omit `--patch-seed` to process JSON only, but that may not resolve country-cache issues in newer versions.

### Settings already match, but Copilot is still missing

Confirm that you are using the repaired profile and check `edge://settings/ai`; some versions use `edge://settings/appearance/copilotAndSidebar`. Also check `edge://policy` and whether `https://copilot.microsoft.com/` works in the same profile. Local settings alone do not establish server-side eligibility. [Microsoft troubleshooting guide](https://learn.microsoft.com/en-us/troubleshoot/microsoft-edge/experience/copilot-icon-missing-sidebar)

### The country changes back after restarting

Subsequent browser or server updates may rewrite the cache. Run diagnostics again to confirm, but do not assume repeated patching is a permanent solution. The script does not lock configuration files or disable browser updates.

### Edge executable not found when reopening

Specify the actual executable with `--edge-exe`. For a custom Beta or Dev data directory, also select the corresponding channel when reopening, or provide that channel's executable explicitly.

## Tests

If you also downloaded the test files from the repository, run:

```powershell
python -m unittest -v test_patch_edge_copilot.py test_edge_copilot_seed.py test_edge_shutdown.py test_edge_menu.py
```

The current implementation has passed **80 automated tests** covering field preservation, malformed-file protection, backups, concurrent-change checks, seed parsing, process shutdown, menus, and reopening. Automated tests use temporary configurations and simulated processes; they do not operate real Edge windows.

The main script has also been copied alone into an isolated temporary directory and verified for menu operation, preview, and simulated configuration repair. Test files are not runtime dependencies.

## Reporting issues

When opening an issue, include:

- Your operating system, Python version, and full Edge version and channel.
- Whether you used the menu or CLI, including the selections or arguments.
- Whether the problem is a missing entry point, a chat that cannot open, or a script error.
- Sanitized diagnostic output; include `--list-processes` output for shutdown problems.
- Whether the problem began after an Edge update and whether country caches change after a restart.

Do not upload complete `Local State`, `Preferences`, browser user data directories, or backup files. Replace usernames and personal directory paths with placeholders before sharing logs.

## References

- [Original patch-edge-copilot project](https://github.com/jiarandiana0307/patch-edge-copilot)
- [Chromium seed reader/writer implementation](https://github.com/chromium/chromium/blob/2bc48d1e3a591d641005e9bc640adfd6c77c517f/components/variations/seed_reader_writer.cc)
- [StoredSeedInfo protobuf definition](https://github.com/chromium/chromium/blob/2bc48d1e3a591d641005e9bc640adfd6c77c517f/components/variations/proto/stored_seed_info.proto)
- [Microsoft: Troubleshoot a missing Copilot icon](https://learn.microsoft.com/en-us/troubleshoot/microsoft-edge/experience/copilot-icon-missing-sidebar)
- [Microsoft: Supported regions and languages in Copilot](https://support.microsoft.com/en-us/microsoft-copilot/supported-regions-and-languages-in-microsoft-copilot)
