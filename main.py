"""PySFTP desktop browser and transfer client."""
from __future__ import annotations

import json
import base64
import hashlib
import traceback
import faulthandler
import os
import posixpath
import re
import secrets
import shlex
import socket
import subprocess
import sys
import tempfile
import time
from collections import deque
from pathlib import Path

import keyring
import paramiko
import requests
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal, QProcess
from PySide6.QtGui import QIcon, QColor, QPalette
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QAbstractItemView, QMenu, QCheckBox, QStyle, QStyledItemDelegate
)

APP_DIR = Path(__file__).resolve().parent
RCLONE = APP_DIR / 'rclone' / 'rclone.exe'
DATA_DIR = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'PySFTP'
PROFILES_FILE = DATA_DIR / 'profiles.json'
SECRET_SERVICE = 'PySFTP-v1'
SETTINGS_FILE = DATA_DIR / 'settings.json'
DEFAULT_SETTINGS = {'max_connections': 8, 'multipart_cutoff_mb': 128, 'multipart_upload': False, 'theme': 'Light'}



# Application colors are kept in one place for consistent dialog and main-window styling.
THEMES = {
    'Light': {'window':'#f5f7fb','surface':'#ffffff','alternate':'#f6f9fc',
              'text':'#243247','muted':'#617089','border':'#dce4ee',
              'accent':'#2578c5','hover':'#eaf2fd','selection':'#dbeafe',
              'track':'#ffffff','running':'#cdeedb','complete':'#d9eafc',
              'failed':'#ffe2e3','inactive':'#f0f3f8'},
    'Dark':  {'window':'#141c28','surface':'#1b2635','alternate':'#202d3d',
              'text':'#e7edf5','muted':'#9eafc3','border':'#33465b',
              'accent':'#4ea3e8','hover':'#2c4158','selection':'#294967',
              'track':'#1b2635','running':'#27634d','complete':'#244a73',
              'failed':'#6e3341','inactive':'#303c4c'}
}


def apply_theme(app, theme):
    theme = theme if theme in THEMES else 'Light'
    colors = THEMES[theme]
    app.setProperty('pysftp_theme', theme)
    palette = QPalette()
    for role, key in ((QPalette.ColorRole.Window, 'window'),
                      (QPalette.ColorRole.WindowText, 'text'),
                      (QPalette.ColorRole.Base, 'surface'),
                      (QPalette.ColorRole.AlternateBase, 'alternate'),
                      (QPalette.ColorRole.Text, 'text'),
                      (QPalette.ColorRole.Button, 'surface'),
                      (QPalette.ColorRole.ButtonText, 'text'),
                      (QPalette.ColorRole.Highlight, 'selection'),
                      (QPalette.ColorRole.HighlightedText, 'text'),
                      (QPalette.ColorRole.ToolTipBase, 'surface'),
                      (QPalette.ColorRole.ToolTipText, 'text')):
        palette.setColor(role, QColor(colors[key]))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(colors['muted']))
    app.setPalette(palette)
    app.setStyleSheet("""
        QWidget { color: %(text)s; font-family: 'Segoe UI'; font-size: 10pt; }
        QMainWindow, QDialog { background: %(window)s; }
        QLabel { background: transparent; }
        QLineEdit, QComboBox, QSpinBox {
            background: %(surface)s; border: 1px solid %(border)s;
            border-radius: 6px; padding: 6px 9px; min-height: 21px;
            selection-background-color: %(selection)s; selection-color: %(text)s;
        }
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTableWidget:focus {
            border: 1px solid %(accent)s;
        }
        QComboBox QAbstractItemView { background: %(surface)s; color: %(text)s;
            selection-background-color: %(selection)s; border: 1px solid %(border)s; }
        QPushButton {
            background: %(surface)s; border: 1px solid %(border)s;
            border-radius: 6px; padding: 6px 12px; min-height: 22px;
        }
        QPushButton:hover { background: %(hover)s; border-color: %(accent)s; }
        QPushButton:pressed { background: %(selection)s; }
        QPushButton:disabled { color: %(muted)s; background: %(alternate)s; }
        QPushButton[primary="true"] { background: %(accent)s; color: #ffffff; border-color: %(accent)s; font-weight: 600; }
        QPushButton[primary="true"]:hover { background: %(accent)s; }
        QTableWidget {
            background: %(surface)s; alternate-background-color: %(alternate)s;
            border: 1px solid %(border)s; border-radius: 7px;
            gridline-color: %(border)s; selection-background-color: %(selection)s;
            selection-color: %(text)s;
        }
        QTableWidget::item { padding: 3px 7px; border: none; }
        QHeaderView::section {
            background: %(alternate)s; color: %(muted)s; font-weight: 600;
            padding: 8px; border: none; border-bottom: 1px solid %(border)s;
        }
        QTableCornerButton::section { background: %(alternate)s; border: none; }
        QMenu { background: %(surface)s; border: 1px solid %(border)s; border-radius: 7px; padding: 5px; }
        QMenu::item { padding: 7px 25px; border-radius: 4px; }
        QMenu::item:selected { background: %(selection)s; }
        QStatusBar { background: %(alternate)s; border-top: 1px solid %(border)s; }
        QSplitter::handle { background: %(border)s; }
        QScrollBar:vertical { background: %(window)s; width: 11px; border: none; }
        QScrollBar::handle:vertical { background: %(border)s; border-radius: 5px; min-height: 24px; margin: 2px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
        QCheckBox { spacing: 9px; }
        QToolTip { background: %(surface)s; color: %(text)s; border: 1px solid %(border)s; padding: 5px; }
    """ % colors)


def winpath(path: Path | str) -> str:
    return str(Path(path).resolve()).replace('\\', '/')


def join_remote(directory: str, name: str) -> str:
    return posixpath.join(directory.rstrip('/') or '/', name)


def remote_transfer_spec(browser_path: str) -> str:
    """Map a browser home-relative path to an SFTP CLI remote path."""
    normalized = posixpath.normpath('/' + browser_path.lstrip('/'))
    return 'remote:' + normalized.lstrip('/')


def fmt_bytes(size: int) -> str:
    n = float(size)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024 or unit == 'TB':
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024
    return str(size)


def hidden_subprocess():
    return subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


class Worker(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.signals = WorkerSignals()
        self.setAutoDelete(False)

    def run(self):
        try:
            self.signals.result.emit(self.fn())
        except Exception as ex:
            self.signals.error.emit(str(ex))
        finally:
            self.signals.finished.emit()


def probe_server_key(host, port):
    """Read the public SSH host key before authentication. No credentials sent."""
    transport = None
    sock = socket.create_connection((host, int(port)), timeout=10)
    try:
        transport = paramiko.Transport(sock)
        transport.start_client(timeout=12)
        key = transport.get_remote_server_key()
        if key is None:
            raise RuntimeError("Server did not offer an SSH host key")
        encoded = key.get_base64()
        fingerprint = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
        return f"{key.get_name()} {encoded}", f"SHA256:{fingerprint}"
    finally:
        if transport is not None:
            transport.close()
        else:
            sock.close()



def quick_delete_remote(profile, password, browser_paths):
    """Delete folders via verified SSH shell when its cwd matches the SFTP root.

    Return False if shell acceleration is unavailable, allowing SFTP purge.
    Never substitute shell paths when the SSH and SFTP views differ.
    """
    host, port = profile['host'], int(profile['port'])
    key_name = host if port == 22 else f'[{host}]:{port}'
    client = paramiko.SSHClient()
    if profile.get('known_hosts'):
        client.load_host_keys(profile['known_hosts'])
    elif profile.get('host_keys'):
        pinned = profile['host_keys']
        for line in pinned.splitlines():
            entry = paramiko.hostkeys.HostKeyEntry.from_line(key_name + ' ' + line.strip())
            if entry is None or entry.key is None:
                raise RuntimeError('Invalid saved SSH host key')
            client.get_host_keys().add(key_name, entry.key.get_name(), entry.key)
    else:
        raise RuntimeError('SSH host-key verification is required for quick deletion')
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        try:
            client.connect(hostname=host, port=port, username=profile['user'],
                           password=password or None, key_filename=profile.get('key_file') or None,
                           look_for_keys=False, allow_agent=True, timeout=12,
                           auth_timeout=12, banner_timeout=12)
        except paramiko.BadHostKeyException:
            raise  # Never silently fall back after a host-key mismatch.
        except (paramiko.AuthenticationException, paramiko.SSHException, OSError):
            return False

        try:
            sftp = client.open_sftp()
            try:
                sftp_root = posixpath.normpath(sftp.normalize('.'))
                # Confirm selected directories stay inside the account's SFTP root,
                # including when a parent component is a symlink.
                for browser_path in browser_paths:
                    components = browser_path.replace('\\', '/').split('/')
                    if any(component in ('.', '..') for component in components):
                        raise ValueError('Unsafe remote deletion path')
                    relative = '/'.join(component for component in components if component)
                    if not relative:
                        raise ValueError('Refusing to delete the remote root directory')
                    resolved = posixpath.normpath(sftp.normalize(relative))
                    if sftp_root != '/' and not resolved.startswith(sftp_root.rstrip('/') + '/'):
                        return False
                    if resolved == sftp_root or resolved == '/':
                        raise ValueError('Refusing to delete the remote root directory')
            finally:
                sftp.close()
            _stdin, stdout, _stderr = client.exec_command('pwd -P', timeout=15)
            shell_root = stdout.read().decode('utf-8', 'replace').strip()
            if stdout.channel.recv_exit_status() != 0 or not shell_root.startswith('/'):
                return False
            shell_root = posixpath.normpath(shell_root)
            if shell_root != sftp_root:
                return False
        except (OSError, EOFError, paramiko.SSHException):
            return False

        targets = []
        for browser_path in browser_paths:
            # Browser paths are rooted at the account's SFTP starting directory.
            # Never allow a parent traversal or deletion of that root.
            parts = browser_path.replace('\\', '/').split('/')
            if any(part in ('.', '..') for part in parts):
                raise ValueError('Unsafe remote deletion path')
            relative = '/'.join(part for part in parts if part)
            if not relative:
                raise ValueError('Refusing to delete the remote root directory')
            target = posixpath.normpath(posixpath.join(shell_root, relative))
            if not target.startswith(shell_root.rstrip('/') + '/') or target == '/':
                raise ValueError('Remote deletion path escapes the connected directory')
            targets.append(target)

        # One remote command, irrespective of how many files each folder contains.
        command = 'rm -rf -- ' + ' '.join(shlex.quote(target) for target in targets)
        _stdin, stdout, stderr = client.exec_command(command, timeout=30)
        stdout.channel.settimeout(3600)
        exit_code = stdout.channel.recv_exit_status()
        if exit_code != 0:
            error = stderr.read(4096).decode('utf-8', 'replace').strip()
            raise RuntimeError(f'SSH quick delete failed (exit {exit_code}): {error}')
        return True
    finally:
        client.close()


class RcloneController:
    def __init__(self):
        self.proc = None
        self.temp_config = None
        self.port = None
        self.user = None
        self.password = None
        self.profile = None
        self.local_auth = None

    def obscure(self, password):
        process = subprocess.run([str(RCLONE), 'obscure', password], capture_output=True,
                                 text=True, creationflags=hidden_subprocess(), timeout=12)
        if process.returncode:
            raise RuntimeError(process.stderr.strip() or 'Unable to obscure password')
        return process.stdout.strip()

    def start(self, profile, password):
        self.stop()
        if not RCLONE.is_file():
            raise RuntimeError(f'Rclone executable not found: {RCLONE}')
        # A temporary configuration is removed on disconnect/exit. Passwords are
        # stored persistently only in the Windows Credential Manager via keyring.
        lines = ['[remote]', 'type = sftp', f'host = {profile["host"]}',
                 f'user = {profile["user"]}', f'port = {profile["port"]}']
        if profile.get('key_file'):
            lines.append(f'key_file = {profile["key_file"]}')
        elif password:
            lines.append(f'pass = {self.obscure(password)}')
        if profile.get('known_hosts'):
            lines.append(f'known_hosts_file = {profile["known_hosts"]}')
        elif profile.get('host_keys'):
            lines.append(f'host_keys = {profile["host_keys"]}')
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='session_', suffix='.conf', dir=str(DATA_DIR))
        self.temp_config = Path(name)
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(lines) + '\n')
        self.profile = profile
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        self.user = 'gui'
        self.password = secrets.token_urlsafe(30)
        self.local_auth = (self.user, self.password)
        args = [str(RCLONE), 'rcd', '--config', str(self.temp_config), '--rc-addr',
                f'127.0.0.1:{self.port}', '--rc-user', self.user,
                '--rc-pass', self.password, '--log-level', 'ERROR']
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                     creationflags=hidden_subprocess())
        for _ in range(50):
            if self.proc.poll() is not None:
                err = self.proc.stderr.read().decode(errors='replace')
                self.stop()
                raise RuntimeError('Rclone failed to start: ' + err[-800:])
            try:
                self.call('core/version', {}, timeout=0.3)
                # Validate remote credentials immediately.
                self.call('operations/list', {'fs': 'remote:', 'remote': profile.get('start_path', '/'),
                                              'opt': {'noMimeType': True}}, timeout=20)
                return
            except requests.RequestException:
                time.sleep(0.1)
            except Exception:
                self.stop()
                raise
        self.stop()
        raise RuntimeError('Rclone did not start in time')

    def call(self, command, args=None, timeout=45):
        if not self.proc or self.proc.poll() is not None:
            raise RuntimeError('Rclone is not running')
        response = requests.post(f'http://127.0.0.1:{self.port}/{command}',
                                 json=args or {}, auth=self.local_auth, timeout=timeout)
        try:
            data = response.json()
        except ValueError:
            raise RuntimeError(response.text[:500])
        if response.status_code >= 400:
            raise RuntimeError(data.get('error', str(data)))
        return data

    def stop(self):
        if self.proc:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=3)
            self.proc = None
        if self.temp_config:
            try:
                self.temp_config.unlink(missing_ok=True)
            except OSError:
                pass
            self.temp_config = None


class ConnectionDialog(QDialog):
    def __init__(self, parent=None, profile=None):
        super().__init__(parent)
        self.setWindowTitle('SFTP connection')
        self.setMinimumWidth(460)
        profile = profile or {}
        layout = QFormLayout(self)
        self.fields = {}
        for key, label, default in [
            ('name', 'Connection name', ''), ('host', 'Hostname', ''),
            ('user', 'Username', ''), ('start_path', 'Starting remote folder', '/'),
            ('key_file', 'SSH private key (optional)', ''),
            ('known_hosts', 'Known hosts file (optional)', '')
        ]:
            widget = QLineEdit(str(profile.get(key, default)))
            self.fields[key] = widget
            layout.addRow(label, widget)
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(int(profile.get('port', 22)))
        layout.insertRow(3, 'Port', self.port)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText('Leave empty to keep saved password')
        layout.addRow('Password', self.password)
        self.save_password = QCheckBox('Store password in Windows Credential Manager')
        self.save_password.setChecked(True)
        layout.addRow('', self.save_password)
        note = QLabel('The first connection will ask you to trust the server fingerprint. '
                      'The key will be remembered and verified on later connections. '
                      'A custom known_hosts file is optional.')
        note.setWordWrap(True)
        layout.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_profile(self):
        profile = {key: field.text().strip() for key, field in self.fields.items()}
        profile['port'] = self.port.value()
        profile['start_path'] = profile['start_path'] or '/'
        return profile

    def accept(self):
        profile = self.get_profile()
        if not profile['name'] or not profile['host'] or not profile['user']:
            QMessageBox.warning(self, 'Missing details', 'Connection name, hostname and username are required.')
            return
        if any('\n' in value or '\r' in value for value in profile.values() if isinstance(value, str)):
            QMessageBox.warning(self, 'Invalid field', 'Connection fields cannot contain line breaks.')
            return
        super().accept()


class TransferProgressDelegate(QStyledItemDelegate):
    """Paint the State cell as a progress background."""
    def paint(self, painter, option, index):
        state = index.data(Qt.ItemDataRole.UserRole) or {}
        status = state.get('status', 'Queued')
        progress = max(0.0, min(100.0, float(state.get('percent', 0))))
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        colors = THEMES.get(QApplication.instance().property('pysftp_theme'), THEMES['Light'])
        painter.fillRect(option.rect, QColor(colors['track']))
        if status == 'Complete':
            painter.fillRect(option.rect, QColor(colors['complete']))
        elif status == 'Running' and progress > 0:
            width = round(option.rect.width() * progress / 100)
            filled = option.rect.adjusted(0, 0, width - option.rect.width(), 0)
            painter.fillRect(filled, QColor(colors['running']))
        elif status.startswith('Failed'):
            painter.fillRect(option.rect, QColor(colors['failed']))
        elif status in ('Cancelled', 'Paused', 'Pausing', 'Cancelling'):
            painter.fillRect(option.rect, QColor(colors['inactive']))
        painter.setPen(QColor(colors['text']))
        text = index.data(Qt.ItemDataRole.DisplayRole) or ''
        if text:
            rect = option.rect.adjusted(7, 0, -7, 0)
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter,
                             option.fontMetrics.elidedText(text, Qt.TextElideMode.ElideRight, rect.width()))
        painter.restore()


class SettingsDialog(QDialog):
    def __init__(self, parent, settings):
        super().__init__(parent)
        self.setWindowTitle('Settings')
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.connections = QSpinBox()
        self.connections.setRange(1, 32)
        self.connections.setValue(settings['max_connections'])
        self.cutoff = QSpinBox()
        self.cutoff.setRange(1, 102400)
        self.cutoff.setSuffix(' MB')
        self.cutoff.setValue(settings['multipart_cutoff_mb'])
        self.theme = QComboBox()
        self.theme.addItems(['Light', 'Dark'])
        self.theme.setCurrentText(settings.get('theme', 'Light'))
        self.upload = QCheckBox('Enable multipart SFTP uploads (server dependent)')
        self.upload.setChecked(settings['multipart_upload'])
        form.addRow('Maximum transfer slots:', self.connections)
        form.addRow('Multipart threshold:', self.cutoff)
        form.addRow('', self.upload)
        form.addRow('Appearance:', self.theme)
        layout.addLayout(form)
        note = QLabel('Settings apply to newly started transfers. Transfers share '
                      'a conservative slot budget across queue items. '
                      'Large single files can use several streams.')
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        return {'max_connections': self.connections.value(),
                'multipart_cutoff_mb': self.cutoff.value(),
                'multipart_upload': self.upload.isChecked(),
                'theme': self.theme.currentText()}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('PySFTP 0.2.5')
        icon_path = APP_DIR / 'assets' / 'pysftp.ico'
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1200, 760)
        self.pool = QThreadPool.globalInstance()
        self.workers = set()  # Preserve QRunnable and signal ownership until delivered.
        self.rc = RcloneController()
        self.profiles = self.load_profiles()
        self.connected_profile_name = None
        self.local_path = Path.home()
        self.remote_path = '/'
        self.local_history = []
        self.remote_history = []
        self.remote_request_id = 0
        self.running_jobs = {}
        self.transfer_queue = []
        self.job_seq = 0
        self.scheduler_busy = False
        self.settings = self.load_settings()
        self.transfer_preflight = False
        self.local_size_generation = 0
        self.connecting = False
        self.last_remote = False
        apply_theme(QApplication.instance(), self.settings['theme'])
        self.setup_ui()
        self.refresh_local()
        self.rebuild_profiles()

    def load_profiles(self):
        try:
            return json.loads(PROFILES_FILE.read_text(encoding='utf-8'))
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def save_profiles(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        PROFILES_FILE.write_text(json.dumps(self.profiles, indent=2), encoding='utf-8')

    def load_settings(self):
        try:
            saved = json.loads(SETTINGS_FILE.read_text(encoding='utf-8'))
            if not isinstance(saved, dict):
                saved = {}
        except (OSError, ValueError):
            saved = {}
        settings = {**DEFAULT_SETTINGS, **saved}
        settings['max_connections'] = max(1, min(32, int(settings['max_connections'])))
        settings['multipart_cutoff_mb'] = max(1, int(settings['multipart_cutoff_mb']))
        settings['multipart_upload'] = bool(settings['multipart_upload'])
        settings['theme'] = settings.get('theme') if settings.get('theme') in THEMES else 'Light'
        return settings

    def edit_settings(self):
        dialog = SettingsDialog(self, self.settings)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.settings = dialog.values()
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps(self.settings, indent=2), encoding='utf-8')
            apply_theme(QApplication.instance(), self.settings['theme'])
            self.queue_table.viewport().update()
            self.next_transfer()

    def start_worker(self, worker):
        self.workers.add(worker)
        # Workers are not auto-deleted. Releasing their signal objects while
        # Qt has queued callbacks can crash the process on Windows.
        worker.signals.finished.connect(lambda w=worker: QTimer.singleShot(
            0, lambda: self.workers.discard(w)))
        self.pool.start(worker)

    def run_task(self, fn, success, label='Operation'):
        worker = Worker(fn)
        worker.signals.result.connect(success)
        worker.signals.error.connect(lambda err: QMessageBox.warning(self, label, err))
        self.start_worker(worker)

    def setup_ui(self):
        main = QWidget()
        self.setCentralWidget(main)
        vertical = QVBoxLayout(main)
        top = QHBoxLayout()
        self.profile_box = QComboBox()
        self.profile_box.setMinimumWidth(140)
        self.profile_box.setMaximumWidth(390)
        add = QPushButton('New / Edit')
        add.clicked.connect(self.edit_profile)
        connect = QPushButton('Connect')
        connect.setProperty('primary', True)
        connect.clicked.connect(self.connect_profile)
        self.disconnect_btn = QPushButton('Disconnect')
        self.disconnect_btn.clicked.connect(self.disconnect_profile)
        top.addWidget(QLabel('Connection:'))
        top.addWidget(self.profile_box, 1)
        top.addWidget(add)
        top.addWidget(connect)
        top.addWidget(self.disconnect_btn)
        settings_btn = QPushButton('Settings')
        settings_btn.clicked.connect(self.edit_settings)
        top.addWidget(settings_btn)
        vertical.addLayout(top)

        paths = QHBoxLayout()
        self.local_back_btn = QPushButton('Back')
        self.local_back_btn.setToolTip('Previous local folder')
        self.local_back_btn.clicked.connect(self.back_local)
        self.local_up_btn = QPushButton('Up')
        self.local_up_btn.setToolTip('Parent local folder')
        self.local_up_btn.clicked.connect(self.up_local)
        self.drive_box = QComboBox()
        self.drive_box.setToolTip('Select a local drive')
        self.drive_box.setMinimumWidth(63)
        self.drive_box.setMaximumWidth(90)
        self.drive_box.activated.connect(self.select_drive)
        self.local_address = QLineEdit()
        self.local_address.returnPressed.connect(self.go_local)
        local_pick = QPushButton('Browse...')
        local_pick.setToolTip('Choose a local folder')
        local_pick.clicked.connect(self.pick_local)

        self.remote_back_btn = QPushButton('Back')
        self.remote_back_btn.setToolTip('Previous remote folder')
        self.remote_back_btn.clicked.connect(self.back_remote)
        self.remote_up_btn = QPushButton('Up')
        self.remote_up_btn.setToolTip('Parent remote folder')
        self.remote_up_btn.clicked.connect(self.up_remote)
        self.remote_address = QLineEdit()
        self.remote_address.returnPressed.connect(self.go_remote)

        left_paths = QHBoxLayout()
        for widget in (self.local_back_btn, self.local_up_btn, self.drive_box,
                       self.local_address, local_pick):
            left_paths.addWidget(widget, 1 if widget is self.local_address else 0)
        right_paths = QHBoxLayout()
        for widget in (self.remote_back_btn, self.remote_up_btn, self.remote_address):
            right_paths.addWidget(widget, 1 if widget is self.remote_address else 0)
        paths.addLayout(left_paths, 1)
        paths.addLayout(right_paths, 1)
        vertical.addLayout(paths)

        self.refresh_drives()
        self.update_navigation_buttons()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.local_table = self.make_table()
        self.remote_table = self.make_table()
        self.local_table.itemDoubleClicked.connect(lambda _: self.open_selection(False))
        self.local_table.itemSelectionChanged.connect(lambda: setattr(self, "last_remote", False))
        self.remote_table.itemDoubleClicked.connect(lambda _: self.open_selection(True))
        self.remote_table.itemSelectionChanged.connect(lambda: setattr(self, "last_remote", True))
        self.local_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.remote_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.local_table.customContextMenuRequested.connect(lambda p: self.show_context(False, p))
        self.remote_table.customContextMenuRequested.connect(lambda p: self.show_context(True, p))
        splitter.addWidget(self.local_table)
        splitter.addWidget(self.remote_table)
        vertical.addWidget(splitter, 1)

        actions = QHBoxLayout()
        for title, callback in [
            ('Refresh', self.refresh_both), ('Download  <', lambda: self.enqueue(False)),
            ('Upload  >', lambda: self.enqueue(True)),
            ('New folder', self.new_folder), ('Rename / Move', self.rename_selected),
            ('Delete', self.delete_selected), ('Cancel transfer', self.cancel_transfer)
        ]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            actions.addWidget(button)
        vertical.addLayout(actions)
        queue_actions = QHBoxLayout()
        queue_actions.addWidget(QLabel('Transfer queue'))
        queue_actions.addStretch()
        clear_completed = QPushButton('Clear completed')
        clear_completed.clicked.connect(self.clear_completed)
        queue_actions.addWidget(clear_completed)
        vertical.addLayout(queue_actions)

        self.queue_table = QTableWidget(0, 6)
        self.queue_table.setHorizontalHeaderLabels(
            ['Transfer', 'State', 'Downloaded', 'Total', 'Speed', 'ETA'])
        header = self.queue_table.horizontalHeader()
        widths = {0: 220, 1: 170, 2: 130, 3: 130, 4: 130, 5: 100}
        for col, width in widths.items():
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            self.queue_table.setColumnWidth(col, width)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.queue_table.setItemDelegateForColumn(1, TransferProgressDelegate(self.queue_table))
        self.queue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.queue_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.queue_table.customContextMenuRequested.connect(self.show_queue_context)
        self.queue_table.setMaximumHeight(220)
        self.queue_table.verticalHeader().setDefaultSectionSize(32)
        self.queue_table.verticalHeader().setVisible(False)
        vertical.addWidget(self.queue_table)
        self.statusBar().showMessage('Ready')
        self.local_address.setText(str(self.local_path))
        self.remote_address.setText(self.remote_path)

    def make_table(self):
        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(['Name', 'Size', 'Modified'])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSortingEnabled(False)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(31)
        return table

    def fill_table(self, table, entries):
        table.setRowCount(0)
        for name, is_dir, size, mod in sorted(entries, key=lambda x: (not x[1], x[0].lower())):
            row = table.rowCount()
            table.insertRow(row)
            item = QTableWidgetItem(name)
            item.setIcon(self.style().standardIcon(
                QStyle.StandardPixmap.SP_DirIcon if is_dir else QStyle.StandardPixmap.SP_FileIcon))
            item.setData(Qt.ItemDataRole.UserRole, {'name': name, 'dir': is_dir, 'size': size})
            table.setItem(row, 0, item)
            table.setItem(row, 1, QTableWidgetItem('' if is_dir else fmt_bytes(size)))
            table.setItem(row, 2, QTableWidgetItem(mod[:19].replace('T', ' ') if mod else ''))

    def refresh_drives(self):
        # Windows drives are presented explicitly; an unavailable drive is not selected.
        import string
        import ctypes
        drive_mask = ctypes.windll.kernel32.GetLogicalDrives() if os.name == 'nt' else 0
        drives = [f'{letter}:\\' for i, letter in enumerate(string.ascii_uppercase)
                  if drive_mask & (1 << i)] if os.name == 'nt' else ['/']
        self.drive_box.blockSignals(True)
        self.drive_box.clear()
        self.drive_box.addItems(drives)
        self.drive_box.blockSignals(False)
        self.update_drive_selection()

    def update_drive_selection(self):
        drive = self.local_path.drive.upper() + '\\' if self.local_path.drive else '/'
        index = self.drive_box.findText(drive)
        if index >= 0:
            self.drive_box.setCurrentIndex(index)

    def update_navigation_buttons(self):
        if not hasattr(self, 'local_back_btn'):
            return
        self.local_back_btn.setEnabled(bool(self.local_history))
        self.local_up_btn.setEnabled(self.local_path.parent != self.local_path)
        connected = bool(self.rc.proc and self.rc.proc.poll() is None)
        self.remote_back_btn.setEnabled(connected and bool(self.remote_history))
        self.remote_up_btn.setEnabled(connected and self.remote_path != '/')
        self.remote_address.setEnabled(connected)

    def change_local(self, requested, record_history=True):
        try:
            target = Path(requested).expanduser().resolve()
            if not target.is_dir():
                raise NotADirectoryError(f'Not a folder: {target}')
            # Verify access before committing the new location.
            entries = self.local_entries(target)
        except (OSError, ValueError) as ex:
            self.local_address.setText(str(self.local_path))
            QMessageBox.warning(self, 'Local folder', str(ex))
            return
        if target != self.local_path and record_history:
            self.local_history.append(self.local_path)
        self.local_path = target
        self.fill_table(self.local_table, entries)
        self.start_local_size_scan(target, entries)
        self.local_address.setText(str(target))
        self.update_drive_selection()
        self.update_navigation_buttons()
        if self.connected_profile_name:
            for profile in self.profiles:
                if profile['name'] == self.connected_profile_name:
                    if profile.get('local_path') != str(target):
                        profile['local_path'] = str(target)
                        self.save_profiles()
                    break

    @staticmethod
    def folder_stats(path):
        """Count a local folder tree without following directory symlinks."""
        total = 0
        files = 0
        folders = 0
        for base, subdirs, names in os.walk(path, followlinks=False):
            real_subdirs = []
            for dirname in subdirs:
                child = Path(base) / dirname
                if child.is_symlink():
                    continue
                folders += 1
                real_subdirs.append(dirname)
            subdirs[:] = real_subdirs
            for filename in names:
                child = Path(base) / filename
                try:
                    if not child.is_symlink():
                        total += child.stat().st_size
                        files += 1
                except OSError:
                    pass
        return files, folders, total

    def start_local_size_scan(self, base, entries):
        """Show local folder sizes as a background calculation, never on the GUI thread."""
        self.local_size_generation += 1
        generation = self.local_size_generation
        directories = [e[0] for e in entries if e[1]]
        if not directories:
            return
        rows = {self.local_table.item(i, 0).text(): i
                for i in range(self.local_table.rowCount())}
        for dirname in directories:
            self.local_table.item(rows[dirname], 1).setText('Calculating...')
        def calculate():
            return [(name, self.folder_stats(base / name)[2]) for name in directories]
        worker = Worker(calculate)
        def done(sizes):
            if generation != self.local_size_generation or self.local_path != base:
                return
            for name, size in sizes:
                row = rows.get(name)
                if row is not None and row < self.local_table.rowCount():
                    item = self.local_table.item(row, 0)
                    if item and item.text() == name:
                        self.local_table.item(row, 1).setText(fmt_bytes(size))
        def failed(message):
            if generation == self.local_size_generation:
                self.statusBar().showMessage(f'Local directory size unavailable: {message}')
        worker.signals.result.connect(done)
        worker.signals.error.connect(failed)
        self.start_worker(worker)

    def local_entries(self, directory):
        entries = []
        for p in directory.iterdir():
            try:
                stat = p.stat()
                entries.append((p.name, p.is_dir(), stat.st_size,
                                time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat.st_mtime))))
            except OSError:
                continue
        return entries

    def refresh_local(self):
        self.change_local(self.local_path, record_history=False)

    def select_drive(self, index):
        self.change_local(self.drive_box.itemText(index))

    def pick_local(self):
        selected = QFileDialog.getExistingDirectory(self, 'Select local folder', str(self.local_path),
            QFileDialog.Option.ShowDirsOnly)
        if selected:
            self.change_local(selected)

    def back_local(self):
        if self.local_history:
            previous = self.local_history.pop()
            self.change_local(previous, record_history=False)

    def up_local(self):
        self.change_local(self.local_path.parent)

    def normalize_remote(self, requested):
        # Rclone paths are POSIX paths. Reject relative navigation above root.
        value = requested.strip().replace('\\', '/')
        if not value.startswith('/'):
            value = '/' + value
        return posixpath.normpath(value)

    def change_remote(self, requested, record_history=True, from_back=False):
        if not self.rc.proc or self.rc.proc.poll() is not None:
            return
        target = self.normalize_remote(requested)
        self.remote_request_id += 1
        request_id = self.remote_request_id
        self.statusBar().showMessage('Loading remote folder...')
        self.remote_address.setText(target)
        worker = Worker(lambda: self.rc.call('operations/list', {'fs': 'remote:', 'remote': target,
                                        'opt': {'noMimeType': True}}, timeout=45))
        def success(result):
            if request_id != self.remote_request_id:
                return
            try:
                entries = [(i['Name'], bool(i.get('IsDir')), int(i.get('Size', 0)),
                            i.get('ModTime', '')) for i in (result.get('list') or [])]
            except (KeyError, ValueError, TypeError) as ex:
                failed(f'Invalid directory response: {ex}')
                return
            if from_back and self.remote_history and self.remote_history[-1] == target:
                self.remote_history.pop()
            elif record_history and target != self.remote_path:
                self.remote_history.append(self.remote_path)
            self.remote_path = target
            self.fill_table(self.remote_table, entries)
            self.remote_address.setText(target)
            self.statusBar().showMessage(f'{len(entries)} remote items')
            self.update_navigation_buttons()
        def failed(err):
            if request_id != self.remote_request_id:
                return
            self.remote_address.setText(self.remote_path)
            self.statusBar().showMessage('Remote navigation failed')
            QMessageBox.warning(self, 'Remote folder', err)
            self.update_navigation_buttons()
        worker.signals.result.connect(success)
        worker.signals.error.connect(failed)
        self.start_worker(worker)

    def refresh_remote(self):
        if not self.rc.proc:
            self.remote_request_id += 1
            self.remote_table.setRowCount(0)
            self.update_navigation_buttons()
            return
        self.change_remote(self.remote_path, record_history=False)

    def refresh_both(self):
        self.refresh_drives()
        self.refresh_local()
        self.refresh_remote()

    def go_local(self):
        self.change_local(self.local_address.text())

    def go_remote(self):
        self.change_remote(self.remote_address.text())

    def back_remote(self):
        if self.remote_history:
            previous = self.remote_history[-1]
            # Consume history only after successful navigation.
            self.change_remote(previous, record_history=False, from_back=True)

    def up_remote(self):
        self.change_remote(posixpath.dirname(self.remote_path.rstrip('/')) or '/')

    def selected(self, remote):
        table = self.remote_table if remote else self.local_table
        rows = {index.row() for index in table.selectionModel().selectedRows()}
        return [table.item(row, 0).data(Qt.ItemDataRole.UserRole) for row in sorted(rows)]

    def open_selection(self, remote):
        items = self.selected(remote)
        if len(items) != 1 or not items[0]['dir']:
            return
        if remote:
            self.change_remote(join_remote(self.remote_path, items[0]['name']))
        else:
            self.change_local(self.local_path / items[0]['name'])

    def rebuild_profiles(self):
        name = self.profile_box.currentText()
        self.profile_box.clear()
        self.profile_box.addItems(p['name'] for p in self.profiles)
        index = self.profile_box.findText(name)
        if index >= 0:
            self.profile_box.setCurrentIndex(index)

    def edit_profile(self):
        index = self.profile_box.currentIndex()
        existing = self.profiles[index] if index >= 0 else None
        choices = QMessageBox.question(self, 'Connection', 'Edit the selected connection?\nChoose No to create a new one.',
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        edit = bool(existing) and choices == QMessageBox.StandardButton.Yes
        dialog = ConnectionDialog(self, existing if edit else None)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        profile = dialog.get_profile()
        if any(p['name'] == profile['name'] for j, p in enumerate(self.profiles) if not edit or j != index):
            QMessageBox.warning(self, 'Duplicate', 'Connection name already exists.')
            return
        if edit:
            previous = self.profiles[index]
            if (previous.get('host'), int(previous.get('port', 22))) == (profile.get('host'), int(profile.get('port', 22))):
                profile['host_keys'] = previous.get('host_keys', '')
            profile['local_path'] = previous.get('local_path', '')
            old = self.profiles[index]['name']
            if old != profile['name']:
                old_password = keyring.get_password(SECRET_SERVICE, old)
                if old_password:
                    keyring.set_password(SECRET_SERVICE, profile['name'], old_password)
                try:
                    keyring.delete_password(SECRET_SERVICE, old)
                except keyring.errors.PasswordDeleteError:
                    pass
            self.profiles[index] = profile
        else:
            self.profiles.append(profile)
        if dialog.password.text() and dialog.save_password.isChecked():
            keyring.set_password(SECRET_SERVICE, profile['name'], dialog.password.text())
        self.save_profiles()
        self.rebuild_profiles()
        self.profile_box.setCurrentText(profile['name'])

    def connect_profile(self):
        index = self.profile_box.currentIndex()
        if index < 0 or self.connecting or self.running_jobs:
            return
        if any(t['status'] in ('Queued', 'Paused', 'Pausing') for t in self.transfer_queue):
            QMessageBox.information(self, 'Transfer queue',
                                    'Cancel pending or paused queue items before changing connections.')
            return
        profile = self.profiles[index].copy()
        password = keyring.get_password(SECRET_SERVICE, profile['name']) or ''
        if not profile.get('key_file') and not password:
            password, ok = QInputDialog.getText(self, 'SSH password', 'Password:', QLineEdit.EchoMode.Password)
            if not ok:
                return
        self.connecting = True
        self.statusBar().showMessage('Connecting...')

        def connect_verified():
            def success(_):
                self.connecting = False
                self.connected_profile_name = profile['name']
                remembered_path = profile.get('local_path')
                if remembered_path:
                    target = Path(remembered_path).expanduser()
                    if target.is_dir():
                        self.local_history.clear()
                        self.change_local(target, record_history=False)
                    else:
                        self.statusBar().showMessage('Saved local folder unavailable: ' + str(target))
                self.remote_history.clear()
                self.remote_path = '/'
                self.statusBar().showMessage('Connected: ' + profile['name'])
                self.change_remote(profile.get('start_path') or '/', record_history=False)
            worker = Worker(lambda: self.rc.start(profile, password))
            worker.signals.result.connect(success)
            worker.signals.error.connect(connection_error)
            self.start_worker(worker)

        def connection_error(err):
            self.connecting = False
            self.statusBar().showMessage('Not connected')
            QMessageBox.warning(self, 'Connection error', str(err))

        if profile.get('known_hosts') or profile.get('host_keys'):
            connect_verified()
            return

        # Probe only on first use, before sending a password. Ask the user
        # to approve the fingerprint, then pin the exact key in the profile.
        worker = Worker(lambda: probe_server_key(profile['host'], profile['port']))
        def on_host_key(result):
            public_key, fingerprint = result
            answer = QMessageBox.question(
                self, 'New SSH server identity',
                f'First connection to {profile["host"]}:{profile["port"]}.\n\n'
                f'Server host-key fingerprint:\n{fingerprint}\n\n'
                'Verify this fingerprint with the server administrator if possible.\n\n'
                'Trust this server and remember its key?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                self.connecting = False
                self.statusBar().showMessage('Connection cancelled')
                return
            # Resolve by profile name so a changed selection cannot overwrite
            # the host key of another saved connection.
            for saved in self.profiles:
                if (saved['name'] == profile['name'] and saved['host'] == profile['host']
                        and int(saved['port']) == int(profile['port'])):
                    saved['host_keys'] = public_key
                    self.save_profiles()
                    profile['host_keys'] = public_key
                    connect_verified()
                    return
            connection_error('Connection profile was modified during verification.')
        worker.signals.result.connect(on_host_key)
        worker.signals.error.connect(connection_error)
        self.start_worker(worker)

    def disconnect_profile(self):
        if self.running_jobs or self.connecting or any(
                t['status'] in ('Queued', 'Paused', 'Pausing') for t in self.transfer_queue):
            QMessageBox.information(self, 'Busy',
                                    'Finish or cancel all running, queued and paused transfers first.')
            return
        self.remote_request_id += 1
        self.rc.stop()
        self.connected_profile_name = None
        self.remote_history.clear()
        self.remote_table.setRowCount(0)
        self.update_navigation_buttons()
        self.statusBar().showMessage('Disconnected')

    def active_side(self):
        return self.last_remote

    def new_folder(self):
        remote = self.active_side()
        name, ok = QInputDialog.getText(self, 'New folder', 'Folder name:')
        if not ok or not name.strip() or name in ('.', '..') or '/' in name or '\\' in name:
            return
        if remote:
            if not self.rc.proc:
                return
            path = join_remote(self.remote_path, name)
            self.run_task(lambda: self.rc.call('operations/mkdir', {'fs': 'remote:', 'remote': path}),
                          lambda _: self.refresh_remote(), 'Create remote folder')
        else:
            try:
                (self.local_path / name).mkdir()
                self.refresh_local()
            except OSError as ex:
                QMessageBox.warning(self, 'Create local folder', str(ex))

    def rename_selected(self):
        remote = self.active_side()
        items = self.selected(remote)
        if len(items) != 1:
            return
        old = items[0]['name']
        new, ok = QInputDialog.getText(self, 'Rename / Move', 'New name (or relative path):', text=old)
        if not ok or not new.strip() or new == old:
            return
        if remote:
            if items[0]['dir']:
                QMessageBox.information(self, 'Folder move', 'Remote directory renaming and moving are not supported.')
                return
            src = join_remote(self.remote_path, old)
            dst = join_remote(self.remote_path, new)
            self.run_task(lambda: self.rc.call('operations/movefile', {'srcFs': 'remote:',
                  'srcRemote': src, 'dstFs': 'remote:', 'dstRemote': dst}),
                  lambda _: self.refresh_remote(), 'Rename remote file')
        else:
            try:
                (self.local_path / old).rename(self.local_path / new)
                self.refresh_local()
            except OSError as ex:
                QMessageBox.warning(self, 'Rename local item', str(ex))

    def delete_selected(self):
        remote = self.active_side()
        items = self.selected(remote)
        if not items:
            return
        if remote and not self.rc.proc:
            return
        answer = QMessageBox.question(self, 'Confirm deletion',
            f'Permanently delete {len(items)} selected item(s) from {"remote" if remote else "local"}?\n'
            'Folders and all their contents will be deleted.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        if remote:
            profile = self.rc.profile.copy()
            password = keyring.get_password(SECRET_SERVICE, profile['name']) or ''
            directory = self.remote_path
            def remove():
                folders = [join_remote(directory, item['name']) for item in items if item['dir']]
                # Execute a single SSH delete for the selected folders when safe.
                accelerated = quick_delete_remote(profile, password, folders) if folders else False
                for item in items:
                    if item['dir'] and accelerated:
                        continue
                    self.rc.call('operations/purge' if item['dir'] else 'operations/deletefile',
                                 {'fs': 'remote:', 'remote': remote_transfer_spec(join_remote(directory, item['name']))[len('remote:'):]},
                                 timeout=3600)
            self.run_task(remove, lambda _: self.refresh_remote(), 'Remote deletion')
        else:
            def remove_local():
                import shutil
                for item in items:
                    path = self.local_path / item['name']
                    if item['dir']:
                        shutil.rmtree(path)
                    else:
                        path.unlink()
            self.run_task(remove_local, lambda _: self.refresh_local(), 'Local deletion')

    def show_context(self, remote, point):
        table = self.remote_table if remote else self.local_table
        if table.itemAt(point) and table.itemAt(point).row() not in {i.row() for i in table.selectedIndexes()}:
            table.selectRow(table.itemAt(point).row())
        menu = QMenu(self)
        menu.addAction('Open folder', lambda: self.open_selection(remote))
        menu.addAction('Download' if remote else 'Upload', lambda: self.enqueue(not remote))
        selected = self.selected(remote)
        if len(selected) == 1 and selected[0]['dir']:
            menu.addAction('Properties...', lambda: self.show_folder_properties(remote, selected[0]['name']))
        menu.addSeparator()
        menu.addAction('New folder', lambda: self.with_side(remote, self.new_folder))
        menu.addAction('Rename / Move', lambda: self.with_side(remote, self.rename_selected))
        menu.addAction('Delete', lambda: self.with_side(remote, self.delete_selected))
        menu.exec(table.viewport().mapToGlobal(point))

    def show_folder_properties(self, remote, name):
        """Calculate directory contents only when Properties is requested."""
        path = join_remote(self.remote_path, name) if remote else self.local_path / name
        profile_name = self.connected_profile_name
        self.statusBar().showMessage(f'Calculating properties for {name}...')
        def calculate():
            if not remote:
                return self.folder_stats(path)
            listing = self.remote_listing(path, recursive=True)
            count_files = sum(1 for entry in listing if not entry.get('IsDir'))
            count_folders = sum(1 for entry in listing if entry.get('IsDir'))
            total = sum(max(0, int(entry.get('Size') or 0)) for entry in listing
                        if not entry.get('IsDir'))
            return count_files, count_folders, total
        worker = Worker(calculate)
        def done(result):
            files, folders, total = result
            # Update the size only if the original folder remains visible.
            # A late response must not modify another directory or connection.
            current_parent = self.remote_path if remote else self.local_path
            original_parent = posixpath.dirname(path) if remote else path.parent
            if current_parent == original_parent and (not remote or self.connected_profile_name == profile_name):
                table = self.remote_table if remote else self.local_table
                for row in range(table.rowCount()):
                    name_item = table.item(row, 0)
                    if name_item and name_item.text() == name and (name_item.data(Qt.ItemDataRole.UserRole) or {}).get('dir'):
                        size_item = table.item(row, 1)
                        if size_item:
                            size_item.setText(fmt_bytes(total))
                            size_item.setToolTip(f'{total:,} bytes')
                        break
            self.statusBar().showMessage(f'Properties calculated for {name}')
            QMessageBox.information(self, 'Folder properties',
                                    f'{path}\n\nFiles: {files:,}\nSubfolders: {folders:,}'
                                    f'\nTotal size: {fmt_bytes(total)} ({total:,} bytes)')
        worker.signals.result.connect(done)
        worker.signals.error.connect(lambda err: QMessageBox.warning(self, 'Folder properties', err))
        self.start_worker(worker)

    def with_side(self, remote, callback):
        self.last_remote = remote
        callback()

    def remote_listing(self, directory, recursive=False):
        """List an SFTP directory; report errors instead of assuming it is empty."""
        data = self.rc.call('operations/list', {
            'fs': 'remote:', 'remote': directory,
            'opt': {'noMimeType': True, 'recurse': recursive}
        }, timeout=120)
        return data.get('list') or []

    def transfer_precheck(self, upload, items, local_base, remote_base):
        """Validate sources and find actual file-level collisions before asking."""
        collisions = []
        profiles = {}
        for item in items:
            name, directory = item['name'], item['dir']
            local_target = local_base / name
            remote_target = join_remote(remote_base, name)
            if upload:
                if directory:
                    if not local_target.is_dir():
                        raise RuntimeError(f'Local source folder no longer exists: {local_target}')
                    source_paths = [p for p in local_target.rglob('*') if p.is_file()]
                    source_files = [p.relative_to(local_target).as_posix() for p in source_paths]
                    source_sizes = [p.stat().st_size for p in source_paths]
                    # A missing remote folder is normal and has no conflicts.
                    parent_items = self.remote_listing(remote_base)
                    entry = next((e for e in parent_items if e['Name'] == name), None)
                    if entry is not None:
                        if not entry.get('IsDir'):
                            raise RuntimeError(f'Remote destination is a file, not a folder: {remote_target}')
                        existing = {e['Path'].lstrip('/') for e in self.remote_listing(remote_target, True)
                                    if not e.get('IsDir')}
                        collisions.extend(f'{name}/{rel}' for rel in source_files if rel in existing)
                else:
                    if not local_target.is_file():
                        raise RuntimeError(f'Local source file no longer exists: {local_target}')
                    source_sizes = [local_target.stat().st_size]
                    entries = self.remote_listing(remote_base)
                    entry = next((e for e in entries if e['Name'] == name), None)
                    if entry is not None:
                        if entry.get('IsDir'):
                            raise RuntimeError(f'Remote destination is a folder, not a file: {remote_target}')
                        collisions.append(name)
            else:
                if directory:
                    # Validate the exact remote source *before* invoking rclone copy.
                    source_entries = self.remote_listing(remote_target, True)
                    source_sizes = [int(e.get('Size') or 0) for e in source_entries if not e.get('IsDir')]
                    if local_target.exists() and not local_target.is_dir():
                        raise RuntimeError(f'Local destination is a file, not a folder: {local_target}')
                    if local_target.is_dir():
                        for entry in source_entries:
                            if entry.get('IsDir'):
                                continue
                            rel = entry['Path'].lstrip('/').replace('/', os.sep)
                            if (local_target / rel).is_file():
                                collisions.append(f'{name}/{entry["Path"].lstrip("/")}')
                else:
                    entries = self.remote_listing(remote_base)
                    entry = next((e for e in entries if e['Name'] == name), None)
                    if entry is None or entry.get('IsDir'):
                        raise RuntimeError(f'Remote source file no longer exists: {remote_target}')
                    source_sizes = [int(entry.get('Size') or 0)]
                    if local_target.is_dir():
                        raise RuntimeError(f'Local destination is a folder, not a file: {local_target}')
                    if local_target.is_file():
                        collisions.append(name)
            profiles[name] = source_sizes
        return collisions, profiles

    def enqueue(self, upload):
        if not self.rc.proc:
            QMessageBox.warning(self, 'Not connected', 'Connect to a server first.')
            return
        if self.transfer_preflight:
            return
        items = [dict(item) for item in self.selected(not upload)]
        if not items:
            QMessageBox.information(self, 'Nothing selected', 'Select files or folders to transfer.')
            return
        local_base = Path(self.local_path)
        remote_base = self.remote_path
        self.transfer_preflight = True
        self.statusBar().showMessage('Checking transfer sources and destination conflicts...')
        worker = Worker(lambda: self.transfer_precheck(upload, items, local_base, remote_base))

        def ready(result):
            collisions, sizes = result
            self.transfer_preflight = False
            policy = 'Overwrite only when sizes differ'
            if collisions:
                choices = ['Skip existing files', 'Overwrite only when sizes differ',
                           'Overwrite all existing files']
                examples = ', '.join(collisions[:4])
                remainder = f' (and {len(collisions)-4} more)' if len(collisions) > 4 else ''
                policy, ok = QInputDialog.getItem(
                    self, 'Destination conflicts',
                    f'{len(collisions)} existing destination file(s):\n{examples}{remainder}\n\n'
                    'How should these files be handled? Directories are merged.',
                    choices, 1, False)
                if not ok:
                    self.statusBar().showMessage('Transfer cancelled')
                    return
            for item in items:
                name = item['name']
                if upload:
                    src = winpath(local_base / name)
                    dst = remote_transfer_spec(join_remote(remote_base, name))
                else:
                    src = remote_transfer_spec(join_remote(remote_base, name))
                    dst = winpath(local_base / name)
                self.job_seq += 1
                task = {'id': self.job_seq, 'name': name, 'src': src, 'dst': dst,
                        'is_dir': item['dir'], 'policy': policy,
                        'sizes': sizes.get(name, []), 'status': 'Queued',
                        'proc': None, 'slots': 0, 'interrupted': False,
                        'progress': 0.0, 'original_total': sum(sizes.get(name, [])),
                        'completed_bytes': 0, 'resume_base': None}
                self.transfer_queue.append(task)
                self.add_transfer_row(name, 'Queued', '', task)
            self.statusBar().showMessage(f'{len(items)} item(s) queued')
            self.next_transfer()

        def failed(error):
            self.transfer_preflight = False
            self.statusBar().showMessage('Transfer validation failed')
            QMessageBox.warning(self, 'Transfer cannot start', error)

        worker.signals.result.connect(ready)
        worker.signals.error.connect(failed)
        self.start_worker(worker)

    def add_transfer_row(self, name, state, detail, task=None):
        row = self.queue_table.rowCount()
        self.queue_table.insertRow(row)
        values = [name, state, '0 B', '-', '-', '-']
        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            if col in (1, 2, 3, 4, 5):
                item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            self.queue_table.setItem(row, col, item)
        if task is not None:
            self.queue_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, task['id'])
        self.set_transfer_progress(row, state, 0, detail)
        return row

    def set_transfer_progress(self, row, status, percent, detail=None):
        if row < 0 or row >= self.queue_table.rowCount():
            return
        item = self.queue_table.item(row, 1)
        if item is None:
            return
        percentage = max(0.0, min(100.0, float(percent)))
        item.setData(Qt.ItemDataRole.UserRole, {'status': status, 'percent': percentage})
        if status == 'Running':
            item.setText(f'{percentage:.0f}%')
        elif status == 'Complete':
            item.setText('Complete')
        elif status == 'Queued':
            item.setText('Queued')
        else:
            item.setText(status)
        if detail:
            item.setToolTip(detail)
        self.queue_table.viewport().update()

    def clear_completed(self):
        for row in range(self.queue_table.rowCount() - 1, -1, -1):
            if self.queue_table.item(row, 1).data(Qt.ItemDataRole.UserRole).get('status') == 'Complete':
                self.queue_table.removeRow(row)

    @staticmethod
    def format_eta(seconds):
        if seconds is None or not isinstance(seconds, (int, float)) or seconds < 0:
            return '-'
        seconds = int(seconds)
        if seconds >= 3600:
            return f'{seconds // 3600}h {(seconds % 3600) // 60}m'
        if seconds >= 60:
            return f'{seconds // 60}m {seconds % 60}s'
        return f'{seconds}s'

    def task_row(self, task):
        for row in range(self.queue_table.rowCount()):
            if self.queue_table.item(row, 0).data(Qt.ItemDataRole.UserRole) == task['id']:
                return row
        return -1

    def update_task(self, task, status, percent=None, detail=None):
        task['status'] = status
        if percent is not None:
            task['progress'] = percent
        row = self.task_row(task)
        if row >= 0:
            self.set_transfer_progress(row, status, task['progress'], detail)

    def required_slots(self, task, available):
        sizes = task['sizes']
        cutoff = self.settings['multipart_cutoff_mb'] * 1024 * 1024
        # Multiple files: one stream/file to avoid exceeding our slot reservation.
        # Single large file: allow its chunks to fill the available slots.
        if len(sizes) == 1 and sizes[0] >= cutoff:
            return available
        return max(1, min(available, max(1, len(sizes))))

    def next_transfer(self):
        if self.scheduler_busy or not self.rc.proc:
            return
        self.scheduler_busy = True
        try:
            limit = self.settings['max_connections']
            occupied = sum(task['slots'] for task in self.running_jobs.values())
            for task in self.transfer_queue:
                if task['status'] != 'Queued':
                    continue
                free = limit - occupied
                if free <= 0:
                    break
                slots = self.required_slots(task, free)
                task['slots'] = slots
                self.launch_transfer(task)
                occupied += slots
            if not self.running_jobs and not any(t['status'] == 'Queued' for t in self.transfer_queue):
                self.refresh_both()
        finally:
            self.scheduler_busy = False

    def launch_transfer(self, task):
        src, dst, is_dir = task['src'], task['dst'], task['is_dir']
        policy, slots = task['policy'], task['slots']
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            stats_port = sock.getsockname()[1]
        stats_auth = ('progress', secrets.token_urlsafe(30))
        sizes = task['sizes']
        cutoff_mb = self.settings['multipart_cutoff_mb']
        multipart = len(sizes) == 1 and sizes[0] >= cutoff_mb * 1024 * 1024
        file_transfers = 1 if multipart else slots
        streams = slots if multipart else 1
        args = ['copy' if is_dir else 'copyto', src, dst,
                '--config', str(self.rc.temp_config), '--stats', '1s', '--stats-one-line',
                '--stats-log-level', 'NOTICE', '--transfers', str(file_transfers),
                '--checkers', str(min(8, max(1, slots))),
                '--multi-thread-streams', str(streams),
                '--multi-thread-cutoff', f'{cutoff_mb}M', '-v',
                '--rc', '--rc-addr', f'127.0.0.1:{stats_port}',
                '--rc-user', stats_auth[0], '--rc-pass', stats_auth[1]]
        if self.settings['multipart_upload'] and not src.startswith('remote:'):
            args.append('--sftp-multithread-upload')
        if task['interrupted']:
            # Completed files are skipped; interrupted files may have to restart.
            args.append('--size-only')
        elif policy == 'Skip existing files':
            args.append('--ignore-existing')
        elif policy == 'Overwrite only when sizes differ':
            args.append('--size-only')
        elif policy == 'Overwrite all existing files':
            args.append('--ignore-times')
        proc = QProcess(self)
        proc.setProgram(str(RCLONE))
        proc.setArguments(args)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        task['proc'] = proc
        task['stop_action'] = None
        self.running_jobs[task['id']] = task
        self.update_task(task, 'Running', task['progress'])
        output_lines = []
        pending_text = ''
        original_total = task.get('original_total', 0)
        previous_completed = task.get('completed_bytes', 0)
        # Rclone restarts its accounting on resume. Keep the queue's original
        # logical size and derive the completed portion from the remaining work.
        resume_base = None if task['interrupted'] else 0
        if original_total:
            row = self.task_row(task)
            if row >= 0:
                self.queue_table.item(row, 3).setText(fmt_bytes(original_total))
        progress_inflight = False
        last_progress = task['progress']
        speed_samples = deque(maxlen=10)
        timer = QTimer(self)
        timer.setInterval(850)

        def apply_stats(stats):
            nonlocal last_progress, resume_base
            if task['proc'] is not proc or task['status'] != 'Running':
                return
            row = self.task_row(task)
            if row < 0:
                return
            run_done = max(0, int(stats.get('bytes') or 0))
            run_total = max(0, int(stats.get('totalBytes') or 0))
            streams_info = stats.get('transferring') or []
            if run_total == 0 and streams_info:
                run_total = sum(max(0, int(item.get('size') or 0)) for item in streams_info)
            raw_speed = max(0.0, float(stats.get('speed') or 0))
            if not raw_speed:
                raw_speed = sum(max(0.0, float(t.get('speedAvg') or 0)) for t in streams_info)
            speed_samples.append(raw_speed)
            speed = sum(speed_samples) / len(speed_samples)

            if original_total:
                if task['interrupted']:
                    # Wait for Rclone's first nonempty workload estimate. This
                    # accounts for files already present at the destination.
                    if run_total > 0:
                        resume_base = max(0, original_total - run_total)
                    elif resume_base is None:
                        # Don't suddenly drop to zero while Rclone scans files.
                        resume_base = previous_completed
                else:
                    resume_base = max(0, original_total - run_total) if run_total else 0
                effective_done = min(original_total, max(0, resume_base + run_done))
                # Rclone may revise its workload estimate during the scan; avoid
                # moving the displayed progress backwards for that reason.
                effective_done = max(previous_completed if task['interrupted'] else 0,
                                     effective_done)
                effective_done = min(original_total, effective_done)
                percent = 100.0 * effective_done / original_total
                display_total = original_total
            else:
                effective_done = run_done
                display_total = run_total
                percent = 100.0 * min(run_done, run_total) / run_total if run_total else 0.0
            task['completed_bytes'] = effective_done
            last_progress = max(last_progress, percent)
            task['progress'] = last_progress
            remaining = max(0, display_total - effective_done)
            # Use the same smoothed speed for ETA and the speed column.
            eta = remaining / speed if speed > 0 else None
            if remaining == 0:
                eta = 0
            for col, value in ((2, fmt_bytes(effective_done)),
                               (3, fmt_bytes(display_total) if display_total else '-'),
                               (4, f'{fmt_bytes(int(speed))}/s' if speed else '-'),
                               (5, self.format_eta(eta))):
                self.queue_table.item(row, col).setText(value)
            self.update_task(task, 'Running', last_progress)

        def poll_stats():
            nonlocal progress_inflight
            if progress_inflight or task['proc'] is not proc or task['status'] != 'Running':
                return
            progress_inflight = True
            def read():
                response = requests.post(f'http://127.0.0.1:{stats_port}/core/stats',
                                         json={}, auth=stats_auth, timeout=3)
                response.raise_for_status()
                return response.json()
            worker = Worker(read)
            def ok(stats):
                nonlocal progress_inflight
                progress_inflight = False
                apply_stats(stats)
            def fail(_):
                nonlocal progress_inflight
                progress_inflight = False
            worker.signals.result.connect(ok)
            worker.signals.error.connect(fail)
            self.start_worker(worker)

        def read_output(final=False):
            nonlocal pending_text
            pending_text += bytes(proc.readAllStandardOutput()).decode('utf-8', errors='replace').replace('\r', '\n')
            parts = pending_text.split('\n')
            pending_text = parts.pop()
            output_lines.extend(line for line in parts if line.strip())
            if final and pending_text.strip():
                output_lines.append(pending_text)

        proc.readyReadStandardOutput.connect(read_output)

        def finished(exit_code, exit_status):
            timer.stop()
            timer.deleteLater()
            read_output(final=True)
            task['proc'] = None
            task['slots'] = 0
            self.running_jobs.pop(task['id'], None)
            action = task.get('stop_action')
            if action == 'pause':
                task['interrupted'] = True
                self.update_task(task, 'Paused', last_progress)
            elif action == 'cancel':
                self.update_task(task, 'Cancelled', last_progress)
            elif exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit:
                row = self.task_row(task)
                if row >= 0:
                    self.queue_table.item(row, 5).setText('0s')
                    if original_total:
                        self.queue_table.item(row, 2).setText(fmt_bytes(original_total))
                        self.queue_table.item(row, 3).setText(fmt_bytes(original_total))
                        task['completed_bytes'] = original_total
                self.update_task(task, 'Complete', 100)
            else:
                errors = [line for line in output_lines if 'ERROR' in line or 'Failed to' in line]
                error_text = (errors[-1] if errors else 'Transfer failed')[-350:]
                self.update_task(task, f'Failed ({exit_code})', last_progress, error_text)
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                with (DATA_DIR / 'transfer-errors.log').open('a', encoding='utf-8') as log:
                    log.write(f'\nSOURCE: {src}\nDESTINATION: {dst}\nCOMMAND: {args[0]}\n'
                              + '\n'.join(output_lines[-150:]) + '\n')
            proc.deleteLater()
            QTimer.singleShot(0, self.next_transfer)

        proc.finished.connect(finished)
        proc.start()
        if not proc.waitForStarted(3000):
            timer.deleteLater()
            self.running_jobs.pop(task['id'], None)
            task['proc'] = None
            task['slots'] = 0
            self.update_task(task, 'Failed to launch', 0, proc.errorString())
            proc.deleteLater()
            QTimer.singleShot(0, self.next_transfer)
            return
        timer.timeout.connect(poll_stats)
        timer.start()
        poll_stats()

    def show_queue_context(self, point):
        row = self.queue_table.rowAt(point.y())
        if row < 0:
            return
        task_id = self.queue_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        task = next((item for item in self.transfer_queue if item['id'] == task_id), None)
        if task is None:
            return
        menu = QMenu(self)
        status = task['status']
        if status in ('Queued', 'Running'):
            menu.addAction('Pause', lambda: self.pause_item(task))
        if status == 'Paused':
            menu.addAction('Resume', lambda: self.resume_item(task))
        if status in ('Queued', 'Running', 'Paused'):
            menu.addAction('Cancel', lambda: self.cancel_item(task))
        if status.startswith('Failed') or status == 'Cancelled':
            menu.addAction('Retry', lambda: self.resume_item(task))
        if not menu.isEmpty():
            menu.exec(self.queue_table.viewport().mapToGlobal(point))

    def pause_item(self, task):
        if task['status'] == 'Queued':
            self.update_task(task, 'Paused')
        elif task['status'] == 'Running' and task['proc'] is not None:
            task['stop_action'] = 'pause'
            task['proc'].kill()
            self.update_task(task, 'Pausing')

    def resume_item(self, task):
        if task['status'] not in ('Paused', 'Cancelled') and not task['status'].startswith('Failed'):
            return
        task['interrupted'] = True
        # Retain the original total and last displayed progress across runs.
        row = self.task_row(task)
        if row >= 0:
            for col, value in ((4, '-'), (5, '-')):
                self.queue_table.item(row, col).setText(value)
        self.update_task(task, 'Queued', task['progress'])
        self.next_transfer()

    def cancel_item(self, task):
        if task['status'] == 'Running' and task['proc'] is not None:
            task['stop_action'] = 'cancel'
            task['proc'].kill()
            self.update_task(task, 'Cancelling')
        elif task['status'] in ('Queued', 'Paused'):
            self.update_task(task, 'Cancelled')
            self.next_transfer()

    def cancel_transfer(self):
        for task in self.transfer_queue:
            if task['status'] in ('Running', 'Queued', 'Paused'):
                self.cancel_item(task)

    def closeEvent(self, event):
        if self.running_jobs:
            answer = QMessageBox.question(self, 'Active transfer',
                'Cancel all active transfers and exit?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            for task in list(self.running_jobs.values()):
                proc = task['proc']
                if proc is not None:
                    task['stop_action'] = 'cancel'
                    proc.kill()
                    proc.waitForFinished(2000)
        self.rc.stop()
        super().closeEvent(event)


_fault_log = None

def main():
    global _fault_log
    # Give Windows a stable identity for taskbar grouping and icon display.
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('PySFTP.Desktop.Client')
        except (AttributeError, OSError):
            pass
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _fault_log = open(DATA_DIR / 'crash.log', 'a', encoding='utf-8', buffering=1)
    try:
        faulthandler.enable(file=_fault_log)
    except (OSError, RuntimeError):
        pass
    def log_exception(typ, value, tb):
        traceback.print_exception(typ, value, tb, file=_fault_log)
        traceback.print_exception(typ, value, tb)
        QMessageBox.critical(None, 'PySFTP error', f'{value}\n\nDetails: {DATA_DIR / "crash.log"}')
    sys.excepthook = log_exception
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    icon_path = APP_DIR / 'assets' / 'pysftp.ico'
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
