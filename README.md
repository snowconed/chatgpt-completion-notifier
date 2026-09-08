# ChatGPT 完了通知（ローカル）

Chrome で開いている ChatGPT の回答終了を検知し、デスクトップ通知と任意のチャイムで知らせる非公式の拡張機能です。

通常の利用に Python、Node.js、API キーは不要です。Chrome 116 以降に対応し、Chrome ウェブストアには公開していません。

## インストール

1. このリポジトリをダウンロードして解凍するか、`git clone` で取得します。
2. Chrome のアドレスバーで `chrome://extensions/` を開きます。
3. 「デベロッパー モード」を ON にします。
4. 「パッケージ化されていない拡張機能を読み込む」で、`manifest.json` が直接入っているフォルダーを選びます。
5. 拡張機能をピン留めし、開いている ChatGPT のタブを再読み込みします。
6. 拡張アイコンを開き、「テスト通知」と「音だけテスト」を試します。

すでにこのフォルダーから拡張機能を読み込んでいる場合、GitHub 連携による再インストールは不要です。利用中はフォルダーを移動・削除しないでください。

詳しい説明は、ダウンロードしたフォルダー内の `guide.html` をブラウザで開くか、[日本語ガイド（テキスト）](README_ja.txt)を参照してください。

## 使い方と監視範囲

- ChatGPT の会話をタブで開いたまま質問を送信します。別タブや別アプリで作業していても監視します。
- 画面上の生成終了と更新の安定を確認し、標準で約 5 秒後に通知します。
- 通知をクリックすると元の会話を開きます。手動停止した回答では通知を抑制します。
- 通知、チャイム、音量、ChatGPT を見ているときの通知は設定画面で変更できます。
- タブを閉じた場合、タブが破棄・凍結された場合、Chrome 終了中や PC スリープ中は監視できません。同じタブで別の会話へ移動すると、元の会話の監視は終了します。
- Windows アプリ版は対象外です。ChatGPT の画面構造の変更や特殊モードによって、検出できないことがあります。

テスト通知も出ない場合は Windows と Chrome の通知設定を確認してください。テスト通知は出るのに回答終了を検出しない場合は、ChatGPT タブを再読み込みし、拡張内の「診断情報（会話本文なし）」を確認してください。

## プライバシー

会話本文・タイトルを通知に表示せず、保存も外部送信もしません。外部 API、広告、アクセス解析は使用していません。設定は `chrome.storage.local`、本文を含まない通知ログとクリック先 URL などは `chrome.storage.session` で扱います。

## 開発とテスト

Node.js 24 で、追加パッケージなしに実行できます。

```sh
node --test tests/detector.test.cjs tests/background.test.cjs
```

GitHub Actions は push とプルリクエスト時に、Windows と Linux で JavaScript の構文確認と上記 37 項目のテストを実行します。

DOM テストは開発者向けの任意の確認です。Python、Playwright、Chromium が別途必要で、ブラウザのパスを指定します。

```sh
python tests/browser_dom.py --chromium "/path/to/chromium" --report tests/browser-results.json
```

Windows では `--chromium` にインストール済み Chrome / Chromium の実行ファイルのパスを指定してください。DOM テストは GitHub Actions の対象に含めていません。

テストの Chrome 拡張 API は模擬です。実際の Windows 通知・音声出力、ログイン済み ChatGPT の最新画面での動作は別途確認が必要です。配布時の検証記録は [tests/TEST_REPORT.md](tests/TEST_REPORT.md) にあります。

## 変更を GitHub に反映する

このフォルダーで変更し、テストした後に実行します。

```sh
git add .
git commit -m "Describe the change"
git push
```

別の PC などで更新した内容を取得するときは、手元の変更をコミットしてから `git pull --ff-only` を実行します。GitHub とフォルダーは常時自動同期ではなく、`push` / `pull` で反映します。

拡張機能のコードを更新した後は、`chrome://extensions/` で拡張機能の再読み込みボタンを押し、ChatGPT のタブも再読み込みしてください。

## ライセンス

[MIT License](LICENSE)
