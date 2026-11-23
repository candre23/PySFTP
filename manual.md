# PySFTP User Manual

## 1. Overview

PySFTP is a two-pane Windows file manager for SFTP servers. The left pane shows your local filesystem, the right pane shows the connected server, and the transfer queue appears underneath. Rclone performs the SFTP operations; the PySide6 interface handles browsing, profiles, conflicts, and progress reporting.

The application needs no system service. It starts a local Rclone control process when you connect and stops it when you disconnect or close the application. Individual transfers may launch additional Rclone child processes while running. The server only needs to expose compatible SFTP access.

## 2. Installation

1. Install Python 3.11 or newer, ensuring the Windows `py` launcher is available.
2. Extract the PySFTP files into a directory such as `E:\pysftp`.
3. Download the Windows AMD64 Rclone executable from <https://rclone.org/downloads/> and place it at `rclone\rclone.exe` inside the PySFTP directory.
4. Double-click `setup.bat`. It creates `.venv` if necessary and installs the packages in `requirements.txt` (`PySide6`, `requests`, `paramiko`, and `keyring`). It does not need PowerShell script-policy changes.
5. Double-click `Launch PySFTP.vbs`. This runs `main.py` through the virtual environment's `pythonw.exe` without a separate console window.

To run with console output for troubleshooting, open a terminal in the project directory and execute:

```powershell
.\.venv\Scripts\python.exe main.py
```

If you already have a working `.venv`, rerunning setup is normally unnecessary. Do not delete the `assets` directory; it contains the application icon.

## 3. Connection profiles

Click **New / Edit** above the file panes. If a profile is selected, the application asks whether to edit it or create a new one.

Provide:

| Field | Purpose |
| --- | --- |
| Connection name | Label shown in the connection dropdown; must be unique |
| Hostname | SFTP server hostname or IP address |
| Username | SSH/SFTP login name |
| Port | SSH port, normally 22 |
| Starting remote folder | Remote browser path to open after login; `/` is the usual starting point |
| SSH private key | Optional path to a supported private key file |
| Known hosts file | Optional existing trusted-hosts file |
| Password | Password for password-based authentication |
| Store password | Store the password in Windows Credential Manager |

Click **Connect** to establish a session. The selected profile controls the remote hostname, authentication, and initial remote directory. The last local directory visited while connected to that profile is restored on subsequent connections, provided the directory still exists.

### SSH host-key trust

On the first connection without a supplied known-hosts file or previously pinned key, PySFTP obtains the public host key and displays a SHA256 fingerprint. Compare this fingerprint with a trusted value from your server administrator when possible, then approve it to save the key. Later connections verify the saved key silently. A changed key should be investigated rather than blindly accepted.

The server supplies the public key, but that alone does not establish that the server is authentic. Passwords stored for profiles are managed by Windows Credential Manager via `keyring`. Connection metadata and the pinned host key are saved separately.

### Disconnecting

Use **Disconnect** to end a session. Finish or cancel running, queued, and paused transfers first; the application prevents disconnecting while that work is pending. Close the application normally to stop its owned Rclone control process.

## 4. Navigating files

### Local pane (left)

Use the **drive dropdown** to switch drives or **Browse...** to pick a folder. Double-click a folder to open it. **Up** goes to the parent and **Back** returns to a previously visited directory. You can also type a path into the address field and press Enter.

Local folder sizes are calculated in the background. Large trees may take time to populate the Size column, but navigating the pane does not wait for those calculations.

### Remote pane (right)

Double-click folders to enter them, use **Up** and **Back**, or type a path into the remote address field and press Enter. The displayed paths are relative to the SFTP account's accessible root, not necessarily absolute paths in the server's operating system. Failed navigation displays an error and keeps the last valid directory.

Remote folder sizes are **not** scanned automatically. Right-click a remote folder and choose **Properties...** to count its files, subfolders, and total recursive size. After the calculation, the folder's Size cell is updated if that folder is still visible. The same Properties command is available for local folders.

## 5. File management

Select an item in either file pane to make that side active. You can select multiple rows for transfers and deletion.

- **Refresh** reloads both panes.
- **New folder** creates a directory on the active side.
- **Rename / Move** renames local items and remote files. Remote directory rename/move is **not supported** in this version.
- **Delete** permanently removes selected items after a confirmation. For directories, this includes the entire subtree.
- **Right-click** a file-pane item for Open folder, Download/Upload, Properties (folders), New folder, Rename / Move, or Delete.

**Deletion warning:** Local recursive deletion uses filesystem removal. For remote folders, PySFTP first tries server-side `rm -rf` over SSH, after checking that the shell's working directory matches the SFTP account root. If SSH commands aren't available or the directory roots differ, it falls back to Rclone's `operations/purge`, which may be slower on large trees. SSH host-key checking is enforced. Deletions are permanent and do not use the Windows Recycle Bin. Verify the selection before confirming.

## 6. Downloads and uploads

1. Connect to an SFTP server.
2. Browse to the source folder on the appropriate side and to the destination folder on the other side.
3. Select one or more files or folders in the source pane.
4. Click **Download <** (remote to local) or **Upload >** (local to remote), or use the source item's context menu.
5. PySFTP checks the source and looks for destination-file conflicts. If there are no conflicting files, the transfer is queued without a conflict dialog.
6. When conflicts exist, choose the applicable policy and proceed.

**Folder names are merged by default.** An existing destination folder does not itself cause a conflict; the dialog appears when files of the same relative path already exist at the destination.

### Conflict options

| Option | Behavior |
| --- | --- |
| Skip existing files | Keep destination files that already exist and transfer missing files |
| Overwrite only when sizes differ | Compare sizes and transfer files whose source/destination sizes differ |
| Overwrite all existing files | Transfer files even where names and metadata match |

The choice applies to that submitted transfer batch. The dialog does not currently offer per-file decisions. Size-only matching does not verify content integrity: same-size but different-content files can be skipped. Source/destination checks happen before queueing; modifying the tree during a transfer may change outcomes.

### Partially completed transfers

Right-click an active queue item and choose **Pause**, then **Resume** when needed. Pause stops the Rclone process for that queue item. On resume, PySFTP uses size-based comparison to avoid retransferring completed files when possible and retains the original displayed total/progress. A partially transferred individual file may need to start again. Pause/resume does not preserve an in-memory multipart byte stream across process restarts.

## 7. Transfer queue

The queue shows **Transfer**, **State**, **Downloaded**, **Total**, **Speed**, and **ETA**. The State cell fills from left to right as progress advances; completed items turn blue. Queued items are unfilled and failed items receive a failure indication.

Right-click a queue item to use actions appropriate to its state:

| Queue state | Available actions |
| --- | --- |
| Queued | Pause, Cancel |
| Running | Pause, Cancel |
| Paused | Resume, Cancel |
| Failed | Retry |
| Cancelled | Retry |
| Complete | Clear via **Clear completed** |

Use **Clear completed** to remove finished rows from the visible queue without interrupting active transfers. The **Cancel transfer** button cancels active, queued, and paused work. The queue is not intended as a persistent cross-application-restart job database.

## 8. Settings

Click **Settings** in the upper-right corner.

| Setting | Default | Meaning |
| --- | --- | --- |
| Maximum transfer slots | 8 | Conservative budget shared among queued tasks; range 1–32 |
| Multipart threshold | 128 MB | Minimum single-file size for allocating multiple streams |
| Multipart SFTP uploads | Off | Allows supported servers to receive multipart uploads |
| Appearance | Light | Switch between Light and Dark themes |

Settings are saved between launches and normally affect newly started transfers. The scheduler can run multiple queue items when it has unreserved slots. A folder's allocated slots remain reserved for the duration of that queue item; this is **not** a hard limit on physical SSH connections and does not dynamically reclaim capacity after every file finishes.

For a single file above the configured threshold, the scheduler can give it multiple parallel streams. For a folder containing multiple files, it generally allocates one stream per file up to the folder's reserved slots. Multipart behavior also depends on the server and Rclone's support.

## 9. Saved data and troubleshooting

PySFTP stores application metadata under:

```text
%LOCALAPPDATA%\PySFTP\
    profiles.json          Connection profiles and remembered local paths
    settings.json          Transfer and theme preferences
    crash.log              Python/crash diagnostics
    transfer-errors.log    Failed transfer output
    session_*.conf         Temporary active Rclone connection configuration
```

Passwords saved with **Store password** are stored through Windows Credential Manager, not in `profiles.json`. Rclone's active temporary configuration may contain an obscured password; Rclone obscuring is not encryption. Protect access to your Windows account and close the app when not in use. Temporary files are normally removed when a session ends cleanly.

If the launcher appears to do nothing, run the command-line invocation from section 2 and inspect `crash.log`. Verify that `rclone\rclone.exe` exists and that `setup.bat` completed successfully. For failed file transfers, inspect `transfer-errors.log`, which records source/destination paths and Rclone errors. For permission errors or missing paths, confirm the account's SFTP-visible root and permissions on the server.

The launcher is a VBScript file that invokes `pythonw.exe`; some endpoint security policies may restrict VBS execution. In that case, create a shortcut that runs `.venv\Scripts\pythonw.exe` with `main.py` as its argument and the project directory as its working directory.

## 10. Current limitations

- Windows-oriented application and setup scripts; Rclone runs locally, no service installation.
- Remote directory move/rename is not implemented.
- Fast remote deletion requires an SSH shell with the same starting directory as SFTP; otherwise recursive deletion uses the slower SFTP purge fallback.
- Transfer conflicts are handled at the batch-policy level, not individually per file.
- Paused jobs resume by restarting the operation, not by preserving active multipart chunk state.
- Connection slots are a scheduling approximation, not a guaranteed count of underlying SSH connections.
- Completed queue entries and progress state are not saved as a persistent restartable queue across launches.
- No built-in auto-updater or packaged standalone executable is provided.
