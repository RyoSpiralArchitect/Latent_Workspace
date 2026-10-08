# V14: 失敗重みの機構解析と、value-centering の一変数比較

2026-10-09。実行は `QUALIFIED_EXECUTION`、科学的判定は **winner: none**。
平均値経路の除去は確認できたが、再学習後の意味的な改善は確認できなかった。
今回の変更対象は workspace の reader。元の Mistral-7B-Instruct-v0.3 は凍結したままで、
Mistral 本体の full update ではない。

## 1. 失敗した重みから分かったこと

旧 bridge の初期値・task128/256・semantic128/256 を固定し、最初の **train 16 世界**で
1,280 traces / 640 reverse-query pairs を計測した。1 state 当たりの 128 pairs は、
16 世界 × 2 sides × 4 query pairs であり、独立した 128 世界ではない。

semantic256 の reader では、逆向きの質問の差が入力にはあるのに、attention/readout を
通ると強く減衰する。slot の幾何学的多様性は初期値より増えており、
「semantic 側の全 slot が完全に潰れた」「RMSNorm が原因」とは結論できない。

`A(q)V = mean(V) + A(q)(V - mean(V))` と分解して介入すると、旧 semantic の
平均絶対 answer-axis gap は **0.313439 → 0.011096**。平均値経路が現状の出力を
大きく担っていた。これは cap を再計算した介入による約 96.46% の減少であり、
因果効果の 96.46% を線形に媒介したという意味ではない。

production の bounded residual 再構成誤差最大は 1.86265e-8（固定許容値 1e-5）、K/V 同時 slot 反転は
完全な不変対照。詳細は [設計凍結記録](REPAIR_DECISION.md) と
[MI 生データ](mechanistic/report.json)。設計時に新規 holdout の得点は見ていない。

## 2. 変更は V の slot 平均除去だけ

memory normalization 後の **V だけ**を masked-slot centering した。
Q/K、パラメータ数 4,200,192、初期値、データ順、損失、AdamW、256-step 予算、cap は据え置き。
失敗重みの続きからではなく、旧条件と同じ初期状態から task / semantic を各 1 回学習した。

旧 semantic と同じ重みを新実装へ載せた実機介入チェックは最大誤差 3.49246e-9 で通過。
これは train の 1 例の許容誤差内等価性であり、全入力での bitwise 同値ではない。
K/V が別入力になったため、FP32 の行列積構成も変わり得る。

## 3. 同じ新規 64 世界での結果

seed 901009。全 256 train + 64 旧 eval との ID・各側の順序・unordered twin・context の
重複は 0。entity と task schema は共有するため、新 entity への汎化試験ではない。
この集合は今回で使用済みとなり、今後の調整後に「未見テスト」として再利用しない。

| 条件 | FP32 正答 / 1,024 | native BF16 正答 / 1,024 | 正しい affected flip / 128（両 head） |
|---|---:|---:|---:|
| 旧 task | 552 | 536 | 0 |
| 改良 task | 552 | 536 | 0 |
| 旧 semantic | 554 | 535 | 1 |
| 改良 semantic | 553 | 537 | 1 |

FP32 の元モデル query-only は 510/1,024。正答数の小差だけでは semantic learning を
認定できない。1,024 件は 64 世界 × 2 sides × 8 queries の相関した観測である。

改良 semantic の FP32 twin 効果は、affected の平均絶対値 **0.0100683** に対して
unaffected **0.0100693** とほぼ同じ。donor 方向の符号は **63 正 / 63 負 / 2 ゼロ**、
符号付き平均は **3.12924e-7**。関係に応じた選択性は得られていない。
旧 semantic の正しい flip も同じ世界 0 / 質問 0 の 1/128 で、新しい成功例ではない。

一方、unrelated が base に与える FP32 gap の平均絶対変化は
**0.0799736 → 0.00545004** と小さくなった。これは限定的な control 改善で、
主課題の方向性獲得とは分けて残す。

## 4. なぜ平均を引くだけでは足りなかったか

学習後も train 16 世界だけで production Q/K/V を再計測した。

| semantic reader の量 | 旧 | 改良 |
|---|---:|---:|
| uniform attention 時の平均 residual L2 | 0.996017 | 6.36774e-8 |
| 通常 attention 時の平均絶対 answer-axis gap | 0.313439 | 0.312837 |
| 逆質問による平均絶対 answer-axis 差 | 8.79100e-8 | 2.67499e-6 |

平均成分の通路はほぼ消えた。しかし新規学習後、残る **非一様 attention の経路**が
再び大きく、ほぼ質問によらない answer-axis bias を出していた。
旧機構がそのまま移動した、あるいは optimizer が意図して迂回した、とは主張しない。
query sensitivity の相対値は増えたが、小さい分母や外れ値の影響もあり、
その比だけを意味理解の改善とは扱わない。

zero-memory は構造上ゼロになるので、その成功だけでも不十分。
fixed carrier は位置ごとに異なる sin/cos slots であり、centering によって必ず消える対照ではない。
norm-matched random も normalization 後の共分散まで一致させた対照ではない。

## 5. 4 ターン生成の手触り

新規世界 0/1 の両側、greedy + matched sampling 3 seeds、fixed / free history、両 head を比較。
旧・改良合計 **1,792 軌道 / 7,168 ターン**。no/yes に制約した生成であり、自由文 chat ではない。
full-prefix 再計算を使い、KV-cache 固有の再帰効果は検証していない。
fixed history は **元世界の正答**を twin を含む全条件へ同じように追加し、
free history は各 branch の実生成を追加する。前者は正答履歴を与えた条件である。

semantic の intact/twin 軌道変化は旧・改良とも、FP32 で fixed **3/16**・free **3/16**、
native で fixed **4/16**・free **4/16**。これらはわずか 2 独立世界の反復である。
別の比較として、全 control を含む旧・改良の対応軌道は 873/896 で生成列が同じ、
23/896 で異なった。以下の代表例が一致しても、全条件の完全一致という意味ではない。

世界 0、side 0、greedy / FP32 の実出力（旧・改良で同じ）：

| 条件 | fixed history | free history |
|---|---|---|
| 元モデル query-only | yes / no / yes / yes | yes / no / yes / no |
| 元モデル inline | yes / yes / yes / yes | yes / yes / yes / yes |
| semantic intact | yes / no / yes / yes | yes / no / yes / no |
| semantic twin | no / no / yes / yes | no / yes / no / yes |

固定質問は Galen/Joren、Cyra/Beryl、Galen/Joren、Cyra/Beryl の比較。
元世界の正答は yes/yes/yes/yes、twin 世界は no/yes/no/yes。
free history では初回分岐後にテキスト履歴も異なる。大きな後続差は、その交絡を含む。
旧重みでも同じ分岐が出るので、今回の改良による新しい再帰的能力とは呼ばない。

## 6. 次の最小ゲート（提案、未実行）

次は平均除去をさらに重ねるのでなく、**質問と memory の相互作用を学べるか**を直接調べる。

1. train-only の小集合で、同一世界の順質問・逆質問を同じ minibatch に置く。
   CE / donor / stability / unrelated 各損失の Q/K/V/writer 勾配の大きさ・方向・相殺を分ける。
2. reader の最終 answer-position 表現だけに頼る経路と、質問内の entity/role を保持した
   query 表現を、最小の reciprocal-query overfit 課題で切り分ける。
3. 学習集合ですら逆質問に応じて補正の向きが変わらない限り、長期学習や base full update に広げない。
   通った場合にのみ新しい固定 holdout を用意し、既存の unaffected/unrelated 対照を維持する。

この試行の否定結果は、workspace 一般の不可能性も、centering の普遍的無効性も示さない。

## 再現・保管

- MI source: `cfd9218`、repair source: `520818b0540579c130050bf7c82c30b82b25feb8`。
- repair 実測 64.218 秒、CUDA peak allocation 14,801,521,152 bytes。
- 元モデルと旧 checkpoint の不変性を検証。新規 checkpoint は各条件 step128/256 のみ、
  合計 67,243,476 bytes。重みは Furnace の `runs/v14/centered_bridge_20261009/` に置き、GitHub へは入れない。
- 今回は旧重みを削除していない。保存単位は条件ごとの最新と 1 個前。
- [SUMMARY.json](SUMMARY.json) は生データから再生成可能。
  [ARTIFACT_INDEX.json](ARTIFACT_INDEX.json) に hash と bytes、[verify.py](verify.py) に独立検証を残す。

```sh
PYTHONPATH=src python3 scripts/summarize_v14_mech_repair.py --check
PYTHONPATH=src python3 provenance/pilots/v14_mech_repair_20261009/verify.py
# Furnace: additionally hash the retained checkpoint bodies
PYTHONPATH=src python3 provenance/pilots/v14_mech_repair_20261009/verify.py --verify-weights
```

実装テスト・実行成立・科学的改善は別の判定である。CI / merge の確認を代用するものでもない。
