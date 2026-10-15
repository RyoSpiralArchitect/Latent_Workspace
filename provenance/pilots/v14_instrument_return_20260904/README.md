# V14: 計器を通し、Mistralへ戻るところまで完了

2026-09-04、事前に固定した一巡を完了。OLMoの成績を追い込まず、
機械的検査と固定screenの完了を根拠にMistralへ戻った。
両モデルの課題ゲートは未通過。本学習・holdout採点・R↔D橋の実験は実施していない。

## 対照結果

各モデル12独立families。容易な1-hopは96回答、難問2/3/4-hopは384回答。
同じfamilyに属する反転、言い換え、alternate edit、両方向質問を独立標本扱いしない。
F0は質問のみ、F1は文脈と質問。いずれも固定されたraw completion形式であり、
OLMoはbase-pretrained、MistralはInstructモデル。モデル間の優劣を測る比較ではない。

| モデル | 機械的検査 | F1・容易 | F1・難問 | 課題ゲート |
| --- | --- | --- | --- | --- |
| OLMo-2-0425-1B | 50/50通過 | 48/96正解、同点0 | 192/384正解、同点0 | NOT_QUALIFIED |
| Mistral-7B-Instruct-v0.3 | 50/50通過 | 42/96正解、同点4 | 166/384正解、同点21 | UNKNOWN、昇格不可 |

同点を勝手にno/yesへ割り当てない。Mistral F1の正答率上下限は容易43.75–47.92%、
難問43.23–48.70%。これは同点の扱いによる上下限であり、統計的信頼区間ではない。
12-family bootstrapの難問F1 95%区間は32.55–59.11%、容易は31.25–60.42%。
Mistralがchance未満だという統計的結論は出さない。

F0はOLMoの両役割で50%。Mistralは容易45正解+6同点/96、難問180正解+24同点/384。
MistralのF1−F0正答率差のfamily区間はいずれも0をまたぐ。
固定の容易・難問ゲートは両モデルとも通らなかった。

## 失敗モードの切り分け

- OLMoはF0/F1とも480/480でyes。全問yesという回答偏りが50%を作っている。
  ただし文脈を足すと候補logitは480/480で変わる。文脈経路が数値的に無反応なのではない。
- Mistralの難問F1はno143/yes220/同点21、容易F1はno16/yes76/同点4。
  全問同じ答えではない。F0→F1で候補logitが変わるのは476/480。
- Mistralの難問では文脈追加による誤→正67件に対して正→誤83件、
  容易では4件に対して10件。同点を含むUNKNOWNはそれぞれ44件、9件。
  数値的に文脈が届くことと、正しく使えていることは別。
- 25件のF1同点は保存したBF16出力で観測された。同じ値を後からFP32へ変換しても
  区別は復元されない。ただし精度違いの対応forwardは未実施なので、BF16丸めが
  同点の原因だとまでは言えない。sidecarのFP32加算がこの課題を解決した証拠もない。
- 聞き方、課題条件、数値精度をまだ分離していない。「チャット整形が原因」や
  「このモデルには能力がない」という結論ではなく、**この固定形式の課題は未適格**。

F0→F1の同じ正解に対するcontext benefitと、同じroute内のoriginal→twin donor gainは
別集計。ここでのcontext twin感度は学習済みmemoryの因果利用ではない。

## 検査として通ったこと

- 各モデル120 records、各route480回答を欠落なく記録。計240回のdirect/wrapper比較は
  すべて有限かつ全logitの数値的一致。bitwise一致や異なるbackend間の一致ではない。
- 全prefixでno/yesが異なる1 tokenとなり、候補を付けてもprefix全体が変わらない。
  未来の正解tokenを書き換えるcanaryは**先頭record×2 routesのみ**で一致した。
  残る238回は未実施としてnullを残しており、全件漏洩検査とは呼ばない。
- 真のbypassの同一出力、zero-upのno-op、固定seedの人工headを開いた経路の影響、
  writer/reader/adapterの勾配所有権、実際のnorm hookの受動性、復元を確認。
- ReaderStateは実際のreader出力・adapter入力と照合した再計算。実K/V hookではない。
  この確認はinline sidecarであり、文脈を持たないdeferred経路の十分性は未検証。
- 一時的な人工headは学習済み重みではない。workspace値、勾配設定、入力を復元。
  常駐baseはobject/version/dtype/device/grad flagの不変を確認し、ディスク上のsnapshotは
  全payload SHA256を実行前後に照合。常駐base全要素の再hashとは区別する。
- sourceはpackage全9 modulesとscripts全42 files、入力・plan・predecessor・生結果をhashで結合。
  prelaunch cache内容を今回のanchorとし、過去の別実験との重み同一性の認証ではない。

CUDA BF16 base + FP32 workspace + CUDA BF16 autocast、SDPAを指定、TF32は無効。
実行されたSDPA kernelの同定はしていない。GPUピーク割当はOLMo約4.94 GiB、
Mistral約17.99 GiB。経過時間は約26.98秒、51.85秒で、hash照合・loadを含み、速度benchmarkではない。
完了後GPU compute processなし、全体使用10 MiBを確認。他のCPU workloadには触れていない。

## 決めていた戻り時と、次の最小ゲート

OLMoで「計器通過＋固定screen完了＋内容不変」を得た時点で戻る。
**正答率はMistral復帰の条件にしない**。今回はその条件を満たし、Mistral元モデルも一巡した。
ここで停止する。OLMo追加条件、prompt探索、holdout採点、学習更新は自動実行しない。

次に計画を切るなら、Mistral自身の課題入口の適格化が最小ゲートになる。
候補はモデル固有のchat整形と固定raw形式の対照、および同じ入力での数値条件の対照。
これらは別々の因子として事前固定し、校正用familyでのみ選定する。
現在のpaired-world encoderはchat-template経路より先に分岐するため、単に
`use_chat_template: true`とするだけでは修正にならない。必要なprompt rendererも
モデル依存のadapterとして本体から分離する、というV14の方針につなげる。

聞き方が通っても、それだけでdeferred memoryやR↔D橋は通らない。
後者にはdeferred経路のintact十分性、学習されたreaderと適切な介入対照の別計画が必要。
B/F1/O3のpure native full-update等価性も棚上げを維持する。

## 記録・再現

- `SUMMARY.json`: 集約値、全生結果hash、検査数。
- `olmo/`, `mistral/`: `report.json`, `cases.jsonl`, `input_parity.jsonl`。
- `validation-local.txt`: 895 passed / CUDA専用3 skipped。
- `validation-furnace.xml`: 今回追加154 tests passed、CPU backendは既定値のまま。
  既存のFurnace CPU BF16 backward制約を修正・解消したという主張ではない。
- 実行コードcommit `8920302`、事前plan `configs/v14/INSTRUMENT_RETURN_PLAN.json`。
  生結果のreportに完全commit、runtime、snapshot、plan/source hashを保存。

既存checkpointの削除・新規downloadは0。重みをGitへ追加していない。
GitHub branch: `SpiralReality/v14-instrument-return-gates`。
