# 地球日記 / Earth Diary

地球が毎朝、昨日一日の自分の体のことを日記に書く。関西弁で。

```
もうええて。昨日、太陽が思いっきり吐いてきたやつが、夜中にまとめて届いた。
秒速969キロやで。顔面に。
……
今日はもう誰とも話したない。寝る。
──
判定：うるさい
```

狂った周波数（hallucination-freqwave-af）の一つ。

---

## これは種です

この作品の芯は、日記そのものよりも一つの操作にあります。

> **あるスケールのデータを、別のスケールの体の文法で読み直す。**

地球の地震・太陽風・磁気嵐を、一人の体の「肩こり」「顔に当たる息」「熱」として読む。
読み替えの表を差し替えれば、まったく別のものが育ちます。

| 差し替える所 | ファイル | 例 |
|---|---|---|
| 何のデータを読むか | `earth_diary/fetch.py` | 自分の街の気温と騒音 / 川の水位 / 自分の心拍と歩数 |
| どんな気分の段階に分けるか | `earth_diary/mood.py` | 静か・達観・正直・うるさい・悟った |
| 誰の声で、どの文法で書くか | `prompts/earth.md` | 地球の関西弁 / 川の京都弁 / 自分の体の標準語 |

フォークして、この三つのどれかを変えてください。それがあなたの木です。

### 気分の決まり方

| 気分 | おおよその条件 | 日記 |
|---|---|---|
| めっちゃ静か | 地磁気Kp≦2、フレアはC未満、地震M5.5未満、M5以上は2回まで | 二〜三行 |
| 達観 | ふつうの日（M5以上の地震は世界で一日4〜5回がふつう） | 大きな時間の目で受け流す |
| 正直 | Kp≧4、フレアM5以上、M6以上の地震、M5以上10回以上 など | 本音が出る。映像に太陽が割り込む |
| うるさい | Kp≧6、Xフレア、M7以上、太陽風800km/s以上 など | 愚痴っぽく長い。映像に太陽が割り込む |
| 悟った | めっちゃ静かな日が3日続いた後、21日に一度まで | めったに来ない |

悟った日はデータだけでは来ません。静けさが積もった後にだけ来ます。

---

## 毎晩の流れ

GitHub Actions が毎晩19時ごろ（日本時間）に回します。

1. データを取る：地震（USGS）、太陽フレア・地磁気・太陽風（NOAA宇宙天気予報センター）、息＝CO2（マウナロア）、冷え＝北極・南極の海氷（NSIDC）、台風・洪水・火山・山火事（GDACS）、月齢（計算）。直近24時間ぶん
2. 気分を決める
3. 日記を書く（Claude）。関西弁 → 英語 → 判定 の順
4. ひまわりが撮った地球の一日を短い動画にする。荒れた日は太陽（NASA SDO）が途中から割り込んでくる
5. `diary/` と `data/` に残す
6. **作者の承認を待つ**。本文入りのIssueを立てるので、届いたメールで日記を読み、**ok** と返信したらXに投稿。返信しなければ投稿されない（日記はリポジトリに残る）。返事はリポジトリの持ち主のものだけを数える

### 人に被害が出たかもしれない日

GDACSの警報がオレンジ・赤の台風・洪水・火山・山火事がある日、または次のどれかに当たる地震があった日は、気分の判定より先に「静かに」書く。笑い・愚痴・軽い比喩は使わない。判定欄にも気分を出さず、太陽も割り込ませない。

- USGSの被害推定（PAGER）が黄色以上
- M7以上
- M6以上で、震源が70km以内と浅い
- 揺れの強さが大きい（人の報告DYFIで6以上。震源の推定MMIで6以上は、被害推定がまだ付いていない時だけ）
- 揺れを感じた報告が1000件以上
- M6以上で津波の注意あり

被害推定は地震の後から付くことがあるので、迷ったら静かな方に倒す作りにしています。それでも最後は人の目で確かめてから投稿します。

## 動かし方

**リポジトリは公開（public）にしてください。** 承認ボタン（Environments の Required reviewers）は、無料・Pro・Team プランでは公開リポジトリでしか使えません。APIキーは Secrets に入れるので、公開しても見えません。

1. Settings → Secrets and variables → Actions に `ANTHROPIC_API_KEY`（Claude の APIキー）を入れる
2. Settings → Environments → New environment で `x-post` を作る
   - Required reviewers は付けない（承認はメールへの ok の返信でする）
   - その環境の Environment secrets に、Xの4つを入れる（承認されるまで投稿の段階からも見えない）

| 名前 | 中身 |
|---|---|
| `X_API_KEY` / `X_API_SECRET` | X 開発者アプリの API Key と Secret |
| `X_ACCESS_TOKEN` / `X_ACCESS_SECRET` | 投稿するアカウントの Access Token と Secret（読み書き権限） |

3. スマホの GitHub アプリで通知をオンにしておく。毎晩「承認待ち」が届くので、開いて日記を読み、Approve を押す
   - 日記の本文は、その実行のまとめ（Summary）に出ます。動画は Artifacts の `earth-diary` から見られます
   - 承認しないまま放っておけば、その日は投稿されません

最初は Actions タブ →「地球日記」→ Run workflow で一回回して、承認待ちのところで中身を確かめてから決めてください。

手元で試す（投稿はしない）：

```
pip install -r requirements.txt
python -m earth_diary.main write
```

## 出典

- 地震：U.S. Geological Survey
- 宇宙天気：NOAA Space Weather Prediction Center
- CO2：NOAA Global Monitoring Laboratory（Mauna Loa）
- 海氷：NSIDC Sea Ice Index
- 台風・洪水・火山・山火事：GDACS（Global Disaster Alert and Coordination System）
- 地球の映像：Japan Meteorological Agency (JMA), NOAA/NESDIS, Colorado State University-CIRA（ひまわり True Color Reproduction）
- 太陽の映像：NASA/SDO and the AIA science team

---

## English

Every morning, the Earth writes a diary about its own body from the day before — in Kansai dialect, with a casual English version.

The seed is one move: **read data from one scale through the body-grammar of another.** Earthquakes become stiff shoulders, solar wind becomes breath on the face, a geomagnetic storm becomes a fever. Fork it and swap the data (`fetch.py`), the moods (`mood.py`), or the voice (`prompts/earth.md`) to grow your own.
