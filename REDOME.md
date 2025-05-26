1. Powershell 管理者権限で下記を実行．
Set-ExecutionPolicy Bypass

2. プロジェクトルートへ移動，仮想環境準備．
.venv/Scripts/activate.ps1
uv sync -U

3. .env ファイルをプロジェクトルートに作成．

3. discord bot を用意し，トークンを自分のものに設定．
DISCORD_BOT_TOKEN=YOUR_DISCORD_BOT_TOKEN

4. LLM API を用意し，API KEY を自分のものに設定．今回は Gemini しか想定していなかったので以下のようにしている．
GOOGLE_API_KEY=YOUR_GOOGLE_API_KEY

5. アプリケーション・ボット起動．
python bot.py

6. ボット導入済みの Discord チャンネル上で，ボットへのメンションを含むメッセージ（ファイルを含む場合はファイルも）を送信する．
※ pdf 等には未対応なのでだれかお願い...

7. ボットからメッセージが来る（このメッセージにリプライすることで，エージェントにフィードバックを送って作業を再開させることができる）．