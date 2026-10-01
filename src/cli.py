"""Command Line Interface (CLI) for Google Classroom Notifier."""

import argparse
import sys

from src.auth import AuthError, get_credentials
from src.classroom import ClassroomClient
from src.config import load_config
from src.discord import DiscordClient
from src.notifier import NotifierService
from src.utils.logger import setup_logger


def cmd_auth(args):
    """Execute OAuth 2.0 login flow to create token.json."""
    config = load_config(args.env_file)
    setup_logger(
        level="INFO",
        log_file=None,
    )
    print("=" * 60)
    print("Google Classroom OAuth 2.0 認証セットアップ")
    print("=" * 60)
    print(f"Credentials JSON: {config.google_credentials_file}")
    print(f"Token Output:    {config.google_token_file}")

    try:
        get_credentials(
            credentials_path=config.google_credentials_file,
            token_path=config.google_token_file,
            interactive_login=True,
        )
        print("✅ 認証が正常に完了しました！")
    except AuthError as e:
        print(f"❌ 認証エラー: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_list_courses(args):
    """List enrolled Google Classroom courses with their IDs."""
    config = load_config(args.env_file)
    logger = setup_logger(level="INFO", log_file=None)
    try:
        creds = get_credentials(
            credentials_path=config.google_credentials_file,
            token_path=config.google_token_file,
            interactive_login=False,
        )
        client = ClassroomClient(creds)
        courses = client.get_enrolled_courses()

        if not courses:
            print("参加している有効なコースが見つかりませんでした。")
            return

        print("\n" + "=" * 80)
        print(f"{'コース名':<35} | {'コースID (course_id)':<20} | {'セクション/説明'}")
        print("-" * 80)
        for c in courses:
            name = c.get("name", "名称不明")[:33]
            cid = c.get("id", "")
            section = c.get("section") or c.get("descriptionHeading") or ""
            print(f"{name:<35} | {cid:<20} | {section}")
        print("=" * 80)
        print(f"合計: {len(courses)} 件のコース\n")
        print(
            "💡 ヒント: これらのコースIDを config/courses.json に記載して個別通知設定が行えます。"
        )
    except AuthError as e:
        print(f"❌ 認証エラー: {e}", file=sys.stderr)
        print("先に 'python -m src.cli auth' を実行してください。", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        logger.error(f"コース一覧の取得に失敗しました: {e}", exc_info=True)
        sys.exit(1)


def cmd_test_notify(args):
    """Send a test notification to verify Discord webhook."""
    config = load_config(args.env_file)
    setup_logger(level="INFO", log_file=None)
    if not config.discord_default_webhook_url:
        print(
            "❌ エラー: DISCORD_DEFAULT_WEBHOOK_URL が設定されていません。\n"
            ".env ファイルを作成し、DISCORD_DEFAULT_WEBHOOK_URL を設定してください。",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Discord Webhook へのテスト送信中: {config.discord_default_webhook_url}")
    client = DiscordClient()
    success = client.send_test_message(
        webhook_url=config.discord_default_webhook_url,
        mention=config.default_mention,
    )
    if success:
        print("✅ テスト通知が正常に送信されました！Discordチャンネルを確認してください。")
    else:
        print(
            "❌ テスト通知の送信に失敗しました。Webhook URL やネットワーク設定を確認してください。",
            file=sys.stderr,
        )
        sys.exit(1)


def cmd_run(args):
    """Execute checking cycle once or in daemon loop."""
    config = load_config(args.env_file)
    has_course_webhook = any(c.webhook_url for c in config.courses if c.enabled)
    if not config.discord_default_webhook_url and not has_course_webhook:
        print(
            "❌ エラー: Discord Webhook URL が設定されていません。\n"
            ".env の DISCORD_DEFAULT_WEBHOOK_URL または config/courses.json の各クラスの webhook_url を設定してください。",
            file=sys.stderr,
        )
        sys.exit(1)

    setup_logger(
        level=config.log_level,
        log_file=config.log_file,
        max_bytes=config.log_max_bytes,
        backup_count=config.log_backup_count,
    )
    service = NotifierService(config)

    if args.daemon:
        service.run_daemon()
    else:
        sent = service.run_once()
        print(f"Run completed. Notifications sent: {sent}")


def main():
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Google Classroom to Discord Notifier",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--env-file",
        type=str,
        default=None,
        help="Path to custom .env file",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # auth
    sub_auth = subparsers.add_parser(
        "auth", help="Authenticate with Google Classroom API (OAuth 2.0)"
    )
    sub_auth.set_defaults(func=cmd_auth)

    # list-courses
    sub_list = subparsers.add_parser(
        "list-courses", help="List all enrolled courses and their course IDs"
    )
    sub_list.set_defaults(func=cmd_list_courses)

    # test-notify
    sub_test = subparsers.add_parser(
        "test-notify", help="Send a test notification to Discord Webhook"
    )
    sub_test.set_defaults(func=cmd_test_notify)

    # run
    sub_run = subparsers.add_parser("run", help="Run notification check")
    sub_run.add_argument(
        "--daemon",
        action="store_true",
        help="Run continuously in background daemon loop",
    )
    sub_run.set_defaults(func=cmd_run)

    args = parser.parse_args()

    if not args.command:
        # 引数なしで実行された場合は run (単発実行) をデフォルトとする
        args.daemon = False
        cmd_run(args)
    else:
        args.func(args)


if __name__ == "__main__":
    main()
