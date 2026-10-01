# Google Classroom to Discord Notifier 📢

Google Classroom の投稿（お知らせ・課題・授業資料）を定期的に検知し、Discord チャンネルへ視認性の高いリッチ Embed 形式で自動通知するシステムです。

学校から配布された Google Workspace for Education アカウントに対応しており、複数のクラスを個別の Discord Webhook やメンション（ロール / ユーザー / @everyone）で柔軟にルーティング・管理できます。

---

## 🌟 主な機能

- **3種類の投稿タイプに完全対応**:
  - 📢 **お知らせ（Announcements）**: 本文・添付リンク・投稿者を表示
  - 📝 **課題（CourseWork）**: 提出期限・配点・説明・添付ファイルを明記
  - 📚 **授業資料（CourseWorkMaterials）**: 配布資料タイトルやリンクを整理して通知
- **視認性に優れた Discord Embed 表示**:
  - 投稿種別ごとのカラーリング（青・赤・緑）
  - Classroom 投稿への直接リンク（`alternateLink`）ボタン付き
- **きめ細やかな複数クラス管理**:
  - クラス（コース）ごとに異なる Discord チャンネル（Webhook）やメンション先（`<@&ロールID>` 等）を設定可能
  - 設定が空の場合は参加中の全アクティブコースを自動検出
- **学校アカウント（Google Workspace for Education）対応**:
  - 管理者によるドメイン委任が不要な OAuth 2.0 デスクトップクライアント方式を採用
  - リフレッシュトークンによる自動更新で、サーバー上での無期限・無人運転が可能
- **堅牢な二重起動・過剰通知防止設計**:
  - 初回同期モード（`INITIAL_SYNC_MARK_AS_READ`）により、導入初回の過去投稿爆撃（大量スパム）を自動防止
  - クロスプラットフォーム対応の排他ファイルロックによるプロセス多重起動防止
  - SQLite WAL モードによる確実な既読・重複管理
  - Discord API レートリミット（429）および Google API 一時的エラー（5xx）に対する自動待機・指数バックオフリトライ

---

## 🛠 技術スタック

- **言語**: Python 3.10+
- **Google API**: `google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2`
- **データ検証**: `pydantic` v2
- **データベース**: SQLite 3 (WAL mode)
- **HTTP / Webhook**: `requests`
- **リント / テスト**: `ruff`, `pytest`, `pytest-mock`
- **CI/CD**: GitHub Actions

---

## 📁 ディレクトリ構成

```text
.
├── .github/
│   └── workflows/
│       └── main.yml              # CI/CD: 構文チェック・型チェック・自動テスト
├── config/
│   ├── courses.example.json      # クラス個別設定のサンプル
│   ├── crontab.example           # cron 定期実行設定例
│   └── logrotate.d/              # Ubuntu Server 用 logrotate 設定
├── src/
│   ├── cli.py                    # CLI コマンド（auth, list-courses, test-notify, run）
│   ├── config.py                 # 環境変数・設定ファイル読込と Pydantic バリデーション
│   ├── auth.py                   # Google OAuth 2.0 認証フロー
│   ├── classroom.py              # Google Classroom API クライアント（IDOR認可チェック付き）
│   ├── discord.py                # Discord Webhook 送信クライアント（Embed整形・レートリミット対策）
│   ├── storage.py                # SQLite 既読・状態管理
│   ├── notifier.py               # ポーリング・差分検知オーケストレーター
│   └── utils/
│       ├── lock.py               # プロセス多重起動防止ロック
│       └── logger.py             # 機密情報マスク機能付きログ設定
├── systemd/
│   ├── classroom-notifier-batch.service # systemd タイマー用ワンショットサービス
│   ├── classroom-notifier-batch.timer   # 5分間隔定期実行タイマー
│   └── classroom-notifier.service       # 常駐デーモン用サービス
├── tests/                        # ユニットテスト一式
├── .env.example                  # 環境変数設定サンプル
├── .gitignore                    # Git 除外設定
├── pyproject.toml                # プロジェクトメタデータ・ツール設定
├── requirements.txt              # 本番依存パッケージ
├── requirements-dev.txt          # 開発・テスト用パッケージ
├── README.md                     # 本ドキュメント
└── DEPLOYMENT_GUIDE.md           # 本番デプロイ・手動オペレーション手順書
```

---

## 🚀 クイックスタート（ローカル環境）

### 1. 依存関係のインストール

```bash
# 仮想環境の作成と有効化
python -m venv .venv
source .venv/bin/activate  # Windows の場合は .venv\Scripts\activate

# パッケージのインストール
pip install -r requirements-dev.txt
```

### 2. 環境変数設定

`.env.example` をコピーして `.env` を作成します。

```bash
cp .env.example .env
```

`.env` 内の `DISCORD_DEFAULT_WEBHOOK_URL` に、通知を受け取りたい Discord チャンネルの Webhook URL を設定してください。

### 3. Google OAuth クライアントの準備

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作成します。
2. **Google Classroom API** を有効化します。
3. **OAuth 同意画面** を設定します（ユーザータイプ: 外部、テストユーザーに対象の学校アカウントを追加）。
4. **認証情報** > **認証情報を作成** > **OAuth クライアント ID** を選択し、アプリケーションの種類を **「デスクトップ アプリ」** にして作成します。
5. ダウンロードした JSON ファイルをプロジェクトルートに `credentials.json` として配置します。

### 4. 初回認証（トークン発行）

```bash
python -m src.cli auth
```

ブラウザが自動的に開くので、通知対象の学校 Google アカウントでログインし、アクセスを許可してください。認証が完了すると `token.json` が生成されます。

### 5. Webhook テスト送信

```bash
python -m src.cli test-notify
```

Discord チャンネルにテスト通知が届けば、連携成功です！

### 6. コース一覧の確認

```bash
python -m src.cli list-courses
```

参加中のコース名とコース ID が一覧表示されます。個別設定を行いたい場合は、コース ID を `config/courses.json` に設定してください。

### 7. ポーリング実行

```bash
# 1回だけチェック実行（バッチ実行）
python -m src.cli run

# バックグラウンド常駐ループ実行（300秒間隔）
python -m src.cli run --daemon
```

---

## 🧪 テストの実行

```bash
# 構文チェック・コードスタイル確認
ruff check .
ruff format --check .

# 自動テストの実行
pytest -v
```

---

## 📖 本番環境（Ubuntu Server）へのデプロイ

自宅サーバーや VPS への配置、cron / systemd timer による自動実行、セキュリティ設定などの全手順は、**[DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)** をご覧ください。

---

## 📄 ライセンス

MIT License
