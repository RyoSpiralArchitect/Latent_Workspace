# V14 position-composition assay

2026-09-13 に、既存の Mistral-7B task / semantic checkpoint を読み取り専用で比較した。固定した 8 cases × 4 controls × 5 answer boundaries × 2 models = 320 rows を一度だけ実行し、各 row で reader update を 7 lanes に分解した。学習、自由生成、checkpoint 選択、weight の書き込み・削除は行っていない。

## 固定した分解

- `full_route`: 全 query position へ一段の reader update を再生
- `answer_boundary_only`: 現在の `Answer:` 境界の最終 token だけ
- `non_boundary_only`: 最終 token 以外の全 position
- `current_query_only`: 現在の固定 query span だけ
- `prior_history_only`: 現在 query より前の履歴だけ
- `oracle_global_answer_axis`: full-sequence local answer gradient への射影
- `oracle_answer_orthogonal`: その直交残差

前半 5 lanes は token 位置だけで決まり、正解 label を使わない。後半 2 lanes は target/reference answer を知る label-aware oracle であり、原因診断専用で、architecture 選択や semantic promotion には使用しない。

learned / positionwise full-Gram random / unrelated-world same-query / sham の 4 controls を retained し、affected と unaffected を別々に集計した。horizon 1–4 の current query は、直前に強制した original-answer token の後から現在の answer boundary までとした。horizon 0 では current query が全 prompt、prior history が空になる。

## 実行と整合性

- source commit: `317c3bbf9ae9f4c2c117e331774b985257abfc8b`
- host: SpiralReality-furnace / RTX 5090
- runtime: 102.713 seconds
- CUDA peak allocated: 15,478,553,600 bytes
- result: `QUALIFIED_EXECUTION`, 320/320 rows
- raw report SHA-256: `c4823a2e3185be9a6fe496d5b871a0e35deb8cff05619146b06ad9c27c312dbc`

全 mechanical checks が true。learned full route と answer-boundary-only の 80 effects は前回 recurrence report を exact に再現した。各 member で、native layer-16 input の `boundary + non-boundary = full` と `current-query + prior-history = full` も bitwise exact。sham は全 lane で exact no-op だった。

## 主結果

前回から固定した semantic / affected / horizon 4 では、learned pair の平均 signed effect が次のようになった。

- full route: `-0.046875`（1 positive / 0 zero / 3 negative）
- answer boundary only: `+0.078125`（3 / 1 / 0）
- non-boundary only: `+0.046875`（2 / 2 / 0）
- current query only: `0.0`（1 / 2 / 1）
- prior history only: `+0.015625`（1 / 2 / 1）

したがって、full route の反転は「non-boundary update が単独で逆向き」だからではない。boundary と non-boundary は単独ではどちらも donor 向きだが、同時に decode すると反転する。

その evidence は composition interaction に明瞭に出た。semantic affected h4 の

`full effect - boundary-only effect - non-boundary-only effect`

は平均 `-0.171875`、3 negative / 1 zero、範囲 `[-0.375, 0]`。4 cases 中 2 cases で positive boundary-only から negative full-route へ実際に反転した。一方、layer-16 native input は exact に加算でき、local-gradient の一次予測も全 4 cases で分解誤差 0 だった。壁は injection 点の線形和ではなく、その後の upper-layer composition と coarse answer-logit readout にある。

label-aware global answer-axis oracle は semantic affected h4 で local-linear mean `+0.003329` を持ったが、observed pair effect は 4/4 cases で 0。正解方向を知る射影でさえ current gain の native readout 格子を越えず、これ自体は deployable bridge にならない。

どの lane でも intact/twin の discrete answer prediction change は 0。semantic answer-boundary h4 は learned `+0.078125`、random `-0.03125`、unrelated `+0.03125`、sham `0` だったが、これは前回結果から選ばれた診断 cell で独立 confirmation ではない。unrelated と unaffected lanes にも粗い刻みの変動が残るため、specificity は未通過。

## 結論と次の最小 gate

科学的 `winner` は引き続き `none`。今回支持されたのは、semantic checkpoint にある二つの donor-directed position component が、full composition の downstream で非加算的に衝突するという局所機構である。semantic memory、generalization、自然会話、capability、position gate の優位性は支持しない。

次は同じ boundary state と position lane を固定し、upper layers 後の final normalized hidden を露出して、native BF16 candidate logits と FP32 two-choice head readout を比較する。negative interaction が FP32 head で消えれば readout precision が橋候補。残れば upper decoder 内で layerwise に interaction が生まれる位置を切ってから、position gate の学習へ進む。
