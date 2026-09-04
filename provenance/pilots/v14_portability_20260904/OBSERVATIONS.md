# V14 portability: OLMo2の実モデル観測（2026-09-04）

## 結論と範囲

OLMo2 BASEのCUDA BF16で、SDPA→eagerの2セルがともに`COMPLETE`となった。
確認できたのは、各セル内のnative実行と分割実行の数値的一致、および有界なnorm観測の非干渉である。
モデル構造が異なる実モデルへ境界実装を持ち出せる基盤が一つ増えたが、workspaceの有用性やR↔D bridgeの証明ではない。
判定全体は[RESULTS.json](RESULTS.json)、証拠とhashは[EVIDENCE_INDEX.json](EVIDENCE_INDEX.json)にまとめる。

## 固定した対象と実行条件

対象は`allenai/OLMo-2-0425-1B`、revision `a1847dff35000b4271fa70afc5db10fd29fedbdf`。
16層・hidden width 2048。保存済みFP32の2 shard、計5,939,687,552 bytesをBF16でロードした。
Furnace RTX 5090、Torch `2.13.0+cu132`、CUDA 13.2、Transformers `5.15.0`。
CPU intra-opは2 threads、interopは観測上24。offline、remote code無効、right padding、cache無効。
source commitは`d7d6f0a50e1888276146aa111ddb5ccd21f1f607`、package fingerprintは
`dfb0279a86de0758ed3a23a046f9daba3f6f2f835766bc3159a14a710e5118d1`。
[事前計画](../../../configs/v14/PORTABILITY_RUN_PLAN.json)のSHA-256は
`e7f6da28213f5d61a57ec8ff2e8d55cde731dabf0819fffae02e51f150b58ca3`。
計画は結果で書き換えず、[LAUNCH_BINDING.json](LAUNCH_BINDING.json)と
[EAGER_LAUNCH_BINDING.json](EAGER_LAUNCH_BINDING.json)で実行を束ねた。

## 観測した一致

| セル | cut 0/8/16の最大logit差 | cut 8の最大全parameter勾配差 | native / split CE |
| --- | ---: | ---: | --- |
| [SDPA](SDPA_CANARY.json) | 各0 | 0 | 3.1775906085968018 / 同値 |
| [eager](EAGER_CANARY.json) | 各0 | 0 | 3.17343807220459 / 同値 |

各cutで固定3 promptの全`3 × 23 × 100352 = 6,924,288` logitsをpadding位置込みで比較した。
cut 8では179 named parameter tensors、1,484,916,736要素すべてに有限な勾配があり、数値差0。
optimizerは構築せず、native勾配をCPUへ保存してからsplit backwardを実行し、終了時に勾配を消去した。
固定許容差はlogits `atol=0.015625, rtol=0.0078125`、勾配 `atol=1e-5, rtol=0.02`で、変更していない。
「数値差0」は符号付きゼロなどを区別するbitwise一致の証明ではない。
またSDPA対eagerのテンソル同一性を比較・立証したものではなく、native CEの差はeager−SDPAで`−0.004152536392211914`。
セル内の境界再現性と、backendによる数値差を分けて扱う必要が実際に見えた。これはeagerの品質優位を示さない。
SDPAの実際のdispatch kernelは未計測のため`UNKNOWN`のままである。

最初の2 promptで各4 tokenを生成し、native/cut 8のtoken IDsが両セルとも一致した。
続きは` room A. The`と` flooded and the roads`。これは短いpipeline確認であり、言語能力やworkspace付き生成の評価ではない。
native logitsに対するnumerics helperのtrue bypassも、両profileで元tensorとdtypeを保った。

norm inventoryは65 module。実測は先頭層の`q_norm`、`k_norm`、`post_attention_layernorm`と最終`model.norm`の4 moduleのみ。
各1回の呼び出しを欠落なく記録し、各pre/postは先頭4096要素に限定した。省略部分や全65 moduleを観測済みとはしない。
この観測を入れたnative出力は元の出力と数値的に完全一致し、unsupported/未完了recordはなかった。
parameter identity/version/`requires_grad`は変わらず、snapshot全12ファイルと実装sourceの事後hash照合も通過した。

## メモリ・経過時間は実行記録

| セル | peak allocated bytes | peak reserved bytes | CLI経過秒 |
| --- | ---: | ---: | ---: |
| SDPA | 6,020,912,128 | 6,144,655,360 | 42.907 |
| eager | 6,020,912,128 | 6,146,752,512 | 38.231 |

経過時間はhash照合・ロード・各チェックを含む。順序とcache状態を揃えた速度比較ではない。
メモリ値は当該processのTorch CUDA allocatorの観測であり、GPU全体使用量や8 GiBのhard capではない。
計画の8 GiB上限はsnapshot payloadに対するもの。hashは重みを復元できるbackupではない。

## テストの失敗も別条件として保持

[LOCAL_VALIDATION.json](LOCAL_VALIDATION.json)は741 passed、CUDA専用3 skipped。
[FURNACE_VALIDATION.json](FURNACE_VALIDATION.json)では既定CPU backendで736 passed・8 failedとなり、
8件ともDNNLのBF16/FP16 backward非対応例外だった。4件はsealed旧参照のbackwardで停止したことが確認できる。
別の2件は参照先行loopのbackward停止だが、XMLだけでは実行中のiterationを特定できない。
残る2件は新wrapperのforward検査後にbackwardで停止した。特定の演算子が原因とは断定しない。
別processでMKLDNNを明示的に無効化すると、同じ744件すべてがpassedとなった。
失敗を削除・skipへ変更せず両記録を残す。既定CPU BF16 backwardを適格化したことにはならず、
後続CUDA canaryはそれぞれ新processの既定CPU backendで実行した。

## 次のゲート

次はモデルごとのworkspace計測経路の適格化と新しいhard-task corpusの適格化である。
その後、読み取り側Rと後続遷移側Dへの入力を独立に交差させ、復元・移植で因果的媒介を検証する。
今回は7B/14Bへの拡張、full workspace generation、学習、重み削除、旧B/F1/O3比較の解決、旧optimizer再開を行っていない。
