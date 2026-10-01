# 本番デプロイ・手動オペレーション手順書 (DEPLOYMENT_GUIDE.md)

本ドキュメントは、**Google Classroom to Discord Notifier** のコード生成完了状態から、GitHub Public リポジトリへの公開、自宅 Ubuntu Server へのデプロイ、Google Cloud 認証設定、systemd タイマー / cron による自動実行、およびヘルスチェックに至る全工程をステップバイステップで解説する運用手順書です。

---

## 目次
- [STEP 1: GitHub リポジトリの初期化と Push](#step-1-github-リポジトリの初期化と-push)
- [STEP 2: アーキテクチャ判定結果と設計理由](#step-2-アーキテクチャ判定結果と設計理由)
- [STEP 3: 実行・ホスティング環境のセットアップ (Ubuntu Server)](#step-3-実行ホスティング環境のセットアップ-ubuntu-server)
- [STEP 4: Google Cloud 認証準備と環境変数（.env）の設定](#step-4-google-cloud-認証準備と環境変数envの設定)
- [STEP 5: CI/CD (GitHub Actions) の設定](#step-5-cicd-github-actions-の設定)
- [STEP 6: 動作確認・ヘルスチェック・運用保守](#step-6-動作確認ヘルスチェック運用保守)

---

## STEP 1: GitHub リポジトリの初期化と Push

GitHub 上に Public リポジトリを作成し、機密情報を排除した状態で初回プッシュを行います。

### 1-1. 機密情報除外の確認 (`.gitignore`)
コミット前に、トークンや秘密鍵、環境変数ファイルが `.gitignore` に含まれていることを確認します。

```bash
# プロジェクトルートで確認
git status --ignored
```

`.env`、`credentials.json`、`token.json`、`data/`、`logs/` が追跡対象外となっていることを必ず確認してください。

### 1-2. Git 初期化と初回コミット

```bash
# Git 初期化
git init

# デフォルトブランチを main に設定
git branch -M main

# ファイルステージングとコミット
git add .
git commit -m "feat: initial commit for Google Classroom to Discord Notifier"
```

### 1-3. GitHub リポジトリの作成とプッシュ
1. [GitHub - New Repository](https://github.com/new) にアクセスします。
2. リポジトリ設定を入力します：
   - **Repository name**: `discord-classroom-notifier`
   - **Description**: `Google Classroomの投稿（お知らせ・課題・資料）をDiscordにEmbed形式で自動通知するシステム。学校アカウント対応・複数クラス個別ルーティング・多重起動防止機能付き。`
   - **Public**: 選択（Public公開）
   - **Initialize this repository with**: すべてチェックを外す（README, .gitignore, license は既に手元にあります）
3. 作成後、以下のコマンドで手元のコードをプッシュします：

```bash
# リモートリポジトリの追加（<YOUR_GITHUB_USERNAME> はご自身のアカウント名に置換）
git remote add origin https://github.com/<YOUR_GITHUB_USERNAME>/discord-classroom-notifier.git

# プッシュ
git push -u origin main
```

---

## STEP 2: アーキテクチャ判定結果と設計理由

### 判定区分: 【区分 2】定期実行バッチ / データ収集・更新処理（自宅 Ubuntu Server）
※ ユーザー要件や運用スタイルに応じて【区分 3】常駐デーモンとしても動作可能なハイブリッド設計

### 選定理由
1. **API レートリミットとコスト最適化**:
   - Google Classroom API の利用にはクォータ制限が存在します。Websocket 等のリアルタイム常駐接続ではなく、5分〜10分間隔の定期ポーリングバッチとすることで、API リクエスト数を必要最小限に抑制し、Google Cloud の無料枠内で恒久的に運用できます。
2. **メモリ・プロセスクラッシュ耐性**:
   - 常駐プロセスは長期稼働に伴うメモリリークやネットワーク切断時のハングアップリスクが伴いますが、ワンショット型バッチ（systemd timer または cron）であれば毎回プロセスがクリーンに終了・起動するため、無人サーバーでの稼働信頼性が極めて高くなります。
3. **学校アカウント（Google Workspace for Education）の制約回避**:
   - 管理者権限を要するサービスアカウントのドメイン全体の委任ではなく、ユーザー権限での「OAuth 2.0 デスクトップクライアント」方式を採用。リフレッシュトークンを利用することで、学校のシステム管理者に特別な申請をすることなく個人で安全に Classroom 投稿を取得できます。
4. **防御的設計（多重起動防止 & 初回爆撃防止）**:
   - ネットワーク遅延や長文処理で処理時間が延びた場合でも、クロスプラットフォーム排他ファイルロック（`SingleInstanceLock`）により同一プロセスの重複実行を完全に遮断します。
   - また、導入初回の大量通知爆撃を防ぐ初回同期フラグ（`INITIAL_SYNC_MARK_AS_READ=true`）を標準装備しています。

---

## STEP 3: 実行・ホスティング環境のセットアップ (Ubuntu Server)

自宅の Ubuntu Server 上に実行環境を構築します。

### 3-1. 必要パッケージのインストール

```bash
# パッケージリスト更新と Python3, venv, git のインストール
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git logrotate
```

### 3-2. アプリケーション配置用ディレクトリの作成とクローン

```bash
# 配置先ディレクトリの作成と権限設定（ubuntu ユーザーの場合）
sudo mkdir -p /opt/classroom-notifier
sudo chown ubuntu:ubuntu /opt/classroom-notifier

# リポジトリのクローン
git clone https://github.com/<YOUR_GITHUB_USERNAME>/discord-classroom-notifier.git /opt/classroom-notifier
cd /opt/classroom-notifier
```

### 3-3. Python 仮想環境の構築と依存関係のインストール

```bash
# 仮想環境作成
python3 -m venv .venv

# pip 更新と本番用パッケージのインストール
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

### 3-4. ログファイルおよびログローテーションの設定

```bash
# ログファイルの作成とパーミッション設定
sudo touch /var/log/classroom-notifier.log /var/log/classroom-notifier.error.log
sudo chown ubuntu:ubuntu /var/log/classroom-notifier*.log
sudo chmod 0640 /var/log/classroom-notifier*.log

# logrotate 設定のコピー
sudo cp config/logrotate.d/classroom-notifier /etc/logrotate.d/classroom-notifier
sudo chmod 0644 /etc/logrotate.d/classroom-notifier
```

### 3-5. 定期実行方式の選定とセットアップ（方式A または 方式B）

#### 【方式 A（推奨）】 systemd タイマーによる定期実行（5分間隔）
プロセスの実行ログが `journalctl` で一元管理でき、実行ジッター（負荷分散）やクラッシュ耐性に優れています。

```bash
# サービスユニットとタイマーユニットの配置
sudo cp systemd/classroom-notifier-batch.service /etc/systemd/system/
sudo cp systemd/classroom-notifier-batch.timer /etc/systemd/system/

# ※ 重要：サービスファイル内のパスとユーザー名を実際の環境に合わせて編集します
# （例: ユーザー名が zyuuuukak1n、配置先が ~/running/classroom-notifier の場合）
sudo nano /etc/systemd/system/classroom-notifier-batch.service
# 以下の4行を実際の環境に合わせて変更して保存します：
#   User=zyuuuukak1n
#   Group=zyuuuukak1n
#   WorkingDirectory=/home/zyuuuukak1n/running/classroom-notifier
#   EnvironmentFile=/home/zyuuuukak1n/running/classroom-notifier/.env
#   ExecStart=/home/zyuuuukak1n/running/classroom-notifier/.venv/bin/python -m src.cli run

# systemd デーモンのリロード
sudo systemctl daemon-reload

# タイマーの有効化と即時起動
sudo systemctl enable --now classroom-notifier-batch.timer

# タイマーのステータス確認
sudo systemctl status classroom-notifier-batch.timer
systemctl list-timers | grep classroom
```

#### 【方式 B】 cron による定期実行
伝統的で軽量な cron による実行も可能です。

```bash
# crontab 編集画面を開く
crontab -e

# 最下行に以下の設定を追加して保存（5分間隔実行 & flockによる多重起動防止）
*/5 * * * * /usr/bin/flock -n /opt/classroom-notifier/data/cron.lock /opt/classroom-notifier/.venv/bin/python -m src.cli run >> /var/log/classroom-notifier.log 2>&1
```

#### 【方式 C（代替案）】 常駐デーモンとして稼働させる場合
定期実行ではなく、常駐ループとして動かしたい場合：

```bash
sudo cp systemd/classroom-notifier.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now classroom-notifier.service
sudo systemctl status classroom-notifier.service
```

---

## STEP 4: Google Cloud 認証準備と環境変数（.env）の設定

### 4-1. Google Cloud Console での OAuth クライアント作成
1. [Google Cloud Console](https://console.cloud.google.com/) にアクセスします。
2. 画面上部から新規プロジェクトを作成（例: `Classroom-Notifier`）。
3. **API とサービス** > **ライブラリ** から **Google Classroom API** を検索し、**有効にする** をクリック。
4. **API とサービス** > **OAuth 同意画面**:
   - User Type: **外部 (External)** を選択して「作成」
   - アプリ名: `Classroom Notifier`
   - ユーザーサポートメール / デベロッパー連絡先: ご自身のメールアドレス
   - スコープ: 空白のまま次へ
   - **テストユーザー**: 通知対象となる**学校の Google アカウント（`~@ed.jp`, `~@ac.jp` 等）**を必ず追加してください。
5. **API とサービス** > **認証情報**:
   - **認証情報を作成** > **OAuth クライアント ID**
   - アプリケーションの種類: **「デスクトップ アプリ」**
   - 名前: `Classroom Notifier Client`
   - 作成後、JSON をダウンロードし、ファイル名を `credentials.json` に変更します。

### 4-2. 初回認証トークン（`token.json`）の取得
Ubuntu Server は SSH 経由（CUI）であることが多いため、**初回認証は手元の Windows / Mac（GUIブラウザがある環境）で実行し、生成された `token.json` をサーバーへ転送する**方法が最も確実で簡単です。

1. **ローカル PC（Windows）上で実行する場合**:
   ```powershell
   # credentials.json を手元のローカルプロジェクトルートに配置後、仮想環境のPythonで実行
   .\.venv\Scripts\python.exe -m src.cli auth

   # または仮想環境を有効化して実行
   # .\.venv\Scripts\Activate.ps1
   # python -m src.cli auth
   ```
   ブラウザが開き、学校アカウントでのログインとアクセス許可を求められます。「許可」をクリックするとローカルに `token.json` が生成されます。

2. **生成された `token.json` と `credentials.json` を Ubuntu Server に安全に転送**:
   ```bash
   # ローカル PC のターミナルから SCP で転送（サーバーIPとユーザー名は環境に合わせて置換）
   scp credentials.json token.json ubuntu@<UBUNTU_SERVER_IP>:/opt/classroom-notifier/
   ```

3. **サーバー上でのパーミッション保護（防御的設計）**:
   ```bash
   # サーバー上で実行（所有者のみ読み書き可能に制限）
   chmod 0600 /opt/classroom-notifier/credentials.json /opt/classroom-notifier/token.json
   ```

### 4-3. 本番環境変数（`.env`）の作成

```bash
cd /opt/classroom-notifier
cp .env.example .env
nano .env  # または vim .env
```

以下のように本番用の設定値を入力します：

```env
# --------------------------------------------------
# Google OAuth 2.0 設定
# --------------------------------------------------
GOOGLE_CREDENTIALS_FILE=/opt/classroom-notifier/credentials.json
GOOGLE_TOKEN_FILE=/opt/classroom-notifier/token.json

# --------------------------------------------------
# Discord Webhook 設定
# --------------------------------------------------
# Discord サーバーのチャンネル設定 > 連携サービス > ウェブフック から取得した URL
DISCORD_DEFAULT_WEBHOOK_URL=https://discord.com/api/webhooks/123456789012345678/abcdefg_hijklmn_opqrstu

# 通知時のデフォルトメンション（ロールID、@everyone、または空白）
DEFAULT_MENTION=<@&112233445566778899>

# --------------------------------------------------
# 取得・通知対象の設定
# --------------------------------------------------
FETCH_ANNOUNCEMENTS=true
FETCH_COURSEWORK=true
FETCH_MATERIALS=true
INITIAL_SYNC_MARK_AS_READ=true

# --------------------------------------------------
# システム設定
# --------------------------------------------------
DATA_DIR=/opt/classroom-notifier/data
LOG_LEVEL=INFO
LOG_FILE=/var/log/classroom-notifier.log
```

保存後、`.env` のパーミッションを厳格化します：

```bash
chmod 0600 /opt/classroom-notifier/.env
```

### 4-4. （任意）複数クラスの個別ルーティング設定 (`config/courses.json`)
特定のクラスごとに送信先 Webhook やメンション先を変えたい場合は、設定ファイルを作成します。

```bash
# 参加中のクラス一覧とコースIDを確認
.venv/bin/python -m src.cli list-courses

# 設定ファイルの作成
cp config/courses.example.json config/courses.json
nano config/courses.json
```

設定例：
```json
[
  {
    "course_id": "123456789012",
    "course_name": "情報ネットワーク工学",
    "enabled": true,
    "webhook_url": "https://discord.com/api/webhooks/111111111111111111/token_alpha",
    "mention": "<@&112233445566778899>",
    "notify_announcements": true,
    "notify_coursework": true,
    "notify_materials": true
  },
  {
    "course_id": "987654321098",
    "course_name": "線形代数学 II",
    "enabled": true,
    "webhook_url": null,
    "mention": "@here"
  }
]
```
※ `webhook_url` や `mention` を `null` にした項目は、`.env` で定義したデフォルト値が適用されます。

---

## STEP 5: CI/CD (GitHub Actions) の設定

リポジトリへの Push や Pull Request 時に自動テストが走るよう、GitHub Secrets の設定を行います。

### 5-1. GitHub Secrets の登録
GitHub のリポジトリ画面から、**Settings** > **Secrets and variables** > **Actions** を開き、**New repository secret** をクリックして以下を登録します：

| Secret 名 | 設定内容 / ダミー値 | 用途 |
| :--- | :--- | :--- |
| `DISCORD_DEFAULT_WEBHOOK_URL` | `https://discord.com/api/webhooks/999999999999999999/dummy-token-for-ci` | CI テスト時の設定検証バリデーション通過用 |

### 5-2. ワークフローの動作確認
1. コードを GitHub にプッシュすると、`.github/workflows/main.yml` が自動トリガーされます。
2. GitHub 上の **Actions** タブを開き、Python 3.10 〜 3.13 の全マトリクス環境で **Ruff Lint Check** および **Pytest Suite** がオールグリーン（Success）になることを確認します。

---

## STEP 6: 動作確認・ヘルスチェック・運用保守

デプロイ完了後、以下の手順で動作確認と監視を行います。

### 6-1. Discord Webhook 疎通テスト

```bash
cd /opt/classroom-notifier
.venv/bin/python -m src.cli test-notify
```
Discord チャンネルに「✅ Google Classroom Notifier テスト通知」という Embed メッセージが届けば疎通成功です。

### 6-2. 手動ポーリング実行（初回同期）

```bash
.venv/bin/python -m src.cli run
```
初回実行時は `INITIAL_SYNC_MARK_AS_READ=true` が有効であるため、既存の投稿が SQLite データベース（`/opt/classroom-notifier/data/state.db`）に既読として記録され、Discord への大量通知が防がれます。

### 6-3. systemd タイマー / サービスのステータス確認

```bash
# タイマーの稼働状況と次回実行時刻を確認
systemctl status classroom-notifier-batch.timer

# 直近のワンショット実行ログを確認
journalctl -u classroom-notifier-batch.service -n 50 --no-pager

# アプリケーションログファイルのリアルタイム監視
tail -f /var/log/classroom-notifier.log
```

### 6-4. 障害時の切り分けとリカバリ

| 症状 | 主な原因 | 対処方法 |
| :--- | :--- | :--- |
| `Valid credentials not found` | `token.json` が未配置または期限切れ | 手元で `python -m src.cli auth` を再実行し、生成された `token.json` をサーバーへ再転送してください。 |
| `HTTP 429 Too Many Requests` | Discord API の一時的なレート制限 | システム内部で自動待機・リトライされます。頻発する場合は監視コース数やポーリング間隔（300秒以上）を見直してください。 |
| `Another instance is already running` | 前回のバッチ処理が長引いてロック中 | 処理が完了するまで自動スキップされます。もしプロセスが異常終了してロックファイルが残った場合は `rm /opt/classroom-notifier/data/notifier.lock` で解除可能です。 |
| `Access denied or course not found` | 指定したコース ID へのアクセス権限がない | 学校アカウントでそのクラスに参加しているか確認し、`python -m src.cli list-courses` で有効なコース ID を再確認してください。 |
