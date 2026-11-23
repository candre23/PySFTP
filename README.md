# PySFTP

A quick and simple two-pane SFTP client for Windows.  More or less a PySide6 GUI for [Rclone](https://rclone.org/) with extra steps.  Built for ease of use, PySFTP has everything you need and nothing you don't.

## Features

- Classic two-pane interface with standard file operations
- Saved server profiles
- Fast recursive folder delete (req. SSH)
- Detailed transfer queue
- Adjustable transfer slots and multipart threshold
- Multipart SFTP uploads (req. server support)
- Light and dark themes, folder properties, and a console-free launcher

<img width="1208" height="798" alt="pysftp" src="https://github.com/user-attachments/assets/da00588b-2db5-4e22-b951-0d3d18c220b1" />

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

## AI \& Safety Disclaimer

The code and documentation included in this project is primarily vibeslop. The human writing this sentence in particular can barely code and doesn't really understand how any of this works. It Works On My Machine and hasn't caused my genitals to explode, but your mileage may vary. I make absolutely no guarantee as to the safety or security of the contents of this project. Use at your own risk. Or don't.

## License

PySFTP is released into the public domain under the [Unlicense](https://github.com/candre23/GenBrowser/blob/main/LICENSE).   

Copyleft 2026   

No Rights Reserved
