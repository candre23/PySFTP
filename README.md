# PySFTP

A lightweight, two-pane SFTP file manager for Windows.  More or less a PySide6 GUI for [Rclone](https://rclone.org/) with extra steps. Browse local and remote files, and manage concurrent uploads and downloads with visible progress.  Built for simplicity and ease of use.

## Features

- Classic two-pane interface with standard file operations
- Saved server profiles
- Fast large-folder delete (req. SSH)
- Detailed transfer queue
- Adjustable transfer slots and multipart threshold
- Multipart SFTP uploads (req. server support)
- Light and dark themes, folder properties, and a console-free launcher

## Requirements

- Windows 10/11
- Python 3.11+ 
- `rclone.exe` 

## Install and run

1. Download/extract this repository to any writable directory.
2. Download `rclone.exe` from [rclone.org/downloads](https://rclone.org/downloads/) and place it in the `rclone` subdirectory.
3. Run `setup.bat` once to create `.venv` and install Python dependencies.
4. Double-click **Launch PySFTP.vbs** to start.


## Documentation

See [manual.md](manual.md) for connections, transfers, settings, limitations, and troubleshooting.

## Notes

PySFTP launches Rclone as an application-owned process. Remote recursive deletion currently uses Rclone's SFTP purge operation, not SSH shell `rm -rf`. Pausing stops the active job; resuming skips completed files where possible, but an interrupted individual file may restart. This project has been tested by its original user, but is not a security-audited or extensively cross-server-tested release.
