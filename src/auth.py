"""Google OAuth 2.0 authentication manager for Google Classroom API."""

import os
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Google Classroom API Read-only Scopes
CLASSROOM_SCOPES: list[str] = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.announcements.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.me.readonly",
    "https://www.googleapis.com/auth/classroom.courseworkmaterials.readonly",
    "https://www.googleapis.com/auth/classroom.rosters.readonly",
]


class AuthError(Exception):
    """Raised when authentication fails or credentials cannot be established."""

    pass


def get_credentials(
    credentials_path: str = "credentials.json",
    token_path: str = "token.json",
    scopes: list[str] | None = None,
    interactive_login: bool = False,
) -> Credentials:
    """Retrieve valid user OAuth credentials.

    If token exists and is valid, returns it.
    If expired, refreshes it automatically.
    If nonexistent and interactive_login is True, triggers browser login flow.
    """
    if scopes is None:
        scopes = CLASSROOM_SCOPES

    token_file = Path(token_path).resolve()
    creds_file = Path(credentials_path).resolve()

    creds: Credentials | None = None

    # 1. 既存のトークンファイルが存在する場合は読み込み
    if token_file.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_file), scopes)
        except Exception:
            creds = None

    # 2. トークンが存在し期限切れならリフレッシュ
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # 更新されたトークンを安全に再保存 (パーミッション 0600)
            _save_credentials_safely(creds, token_file)
            return creds
        except Exception:
            creds = None

    # 3. 有効なトークンがあれば返却
    if creds and creds.valid:
        return creds

    # 4. トークンがなく、対話認証が許可されていない場合はエラー
    if not interactive_login:
        raise AuthError(
            f"Valid credentials not found at '{token_path}'. "
            "Please run 'python -m src.cli auth' to authenticate first."
        )

    # 5. 対話認証（初回セットアップ時）
    if not creds_file.exists():
        raise AuthError(
            f"Google OAuth client credentials file not found at: '{credentials_path}'. "
            "Download 'credentials.json' from Google Cloud Console (Desktop application type)."
        )

    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), scopes)
        # ローカルサーバー起動で認証（ブラウザ自動オープン）
        print("\n=== Google Classroom 認証を開始します ===")
        print("ブラウザが自動的に開かない場合は、コンソールに表示されるURLへアクセスしてください。")
        creds = flow.run_local_server(
            port=0,
            access_type="offline",
            prompt="consent",
            open_browser=True,
        )
        _save_credentials_safely(creds, token_file)
        print(f"認証に成功しました。トークンを保存しました: {token_file}\n")
        return creds
    except Exception as e:
        raise AuthError(f"OAuth 2.0 authorization flow failed: {e}") from e


def _save_credentials_safely(creds: Credentials, destination: Path) -> None:
    """Save credentials to disk with restrictive file permissions (read/write only by owner)."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(creds.to_json(), encoding="utf-8")

    # POSIXシステム（Ubuntu Server等）でのパーミッションを 0600 (所有者のみ読み書き) に設定
    if sys.platform != "win32":
        try:
            os.chmod(str(destination), 0o600)
        except OSError:
            pass
