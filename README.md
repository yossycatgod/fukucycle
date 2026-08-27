# fukucycle

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/yossycatgod/fukucycle)

公開版: https://fukucycle.onrender.com/

都市鉱山を「探す・回収する・学ぶ」位置情報型プロダクトです。現在地から回収スポットの方向と距離を確認し、地域のスポットや学習コラムを利用者自身が追加できます。

## 起動

```bash
python3 -m pip install -r requirements.txt
python3 test_20260709.py
```

## PCを一時サーバーにする

同じWi-Fi内へ公開する場合：

```bash
./serve_local.sh
```

PCのローカルIPを確認し、スマートフォンから `http://PCのIP:8080` を開きます。macOSのファイアウォール確認が表示された場合はPythonの受信接続を許可してください。

インターネットへ一時公開する場合：

```bash
brew install cloudflared
./serve_public.sh
```

表示された `https://...trycloudflare.com` が一時URLです。ターミナルを閉じると公開も終了します。審査提出用の恒久URLには一時トンネルを使わず、正式なホスティングへ移行してください。

## Renderへ公開

このリポジトリには `render.yaml` が含まれています。RenderのNew BlueprintからGitHubリポジトリを選択すると、無料Webサービスとしてビルドできます。

無料環境のファイル保存は一時的です。再起動後も審査用アカウントはビルド時に再生成されますが、一般ユーザーが追加したアカウント・投稿・スポットは失われる場合があります。本番運用では共有データベースへ移行してください。

## データと外部サービス

- 地図: OpenStreetMap
- 住所検索: Nominatim
- 端末内保存: `collection_points.json`、`urban_mine_columns.json`、`m3ow_state.json`
- 位置情報は利用者の許可後にのみ取得します。

## 主な体験

1. 現在地を取得する
2. 矢印と距離を頼りに回収スポットを探す
3. 現地でチェックインする
4. 製品に含まれる貴金属を素材ラボで比較する
5. 都市鉱山について学び、コラムを投稿する

## オンライン機能

- 同じサーバープロセスへ接続中のユーザー数を表示します。
- プロフィールで位置共有を有効にしたユーザーだけが、匿名アバターとして地図に表示されます。
- 回収スポットとコミュニティコラムの追加は、接続中の他ユーザーへ数秒以内に同期されます。
- 切断したユーザーは約15秒でオンライン表示から自動的に削除されます。

## 生成AIの利用

開発支援にOpenAI Codexを使用しています。応募時は、UI実装・コード整理・ドキュメント作成など、使用範囲を応募フォームへ正確に記載してください。
