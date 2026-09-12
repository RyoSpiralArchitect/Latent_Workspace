# V14 readout-precision assay

2026-09-13 に SpiralReality-furnace の RTX 5090 で、既存 Mistral-7B task / semantic checkpoint を読み取り専用で比較した。固定済みの 8 cases × 4 controls × 5 horizons × 2 models = 320 rows と、各 row の 7 position lanes を一度だけ実行した。学習、自由生成、weight の書き込み・削除、結果を見た後の lane 選択は行っていない。

## 今回分離したもの

各 boundary state について Mistral の上位層 16–31 と最終 RMSNorm を一度だけ実行し、その同一 final-normalized hidden を次の二つで読んだ。

- `native_bf16_head`: 既存結果と同じ全系列・全語彙 lm_head を BF16 autocast 下で実行
- `fp32_choice_head`: 同じ最終 token hidden と固定 `no` / `yes` weight rows だけを FP32 にして実行

FP32 側は full-FP32 decoder ではなく、最終二択射影だけの診断 lane である。native 側は CUDA kernel shape を含めて前回と同じに保ち、前回 320 rows の base / intact / twin / effect readout を全て exact に再現することを必須 gate とした。

## 実行と整合性

- source commit: `9ca8c195c76b0d0d77db4c699e6e7722345dee13`
- runtime: 65.379 seconds
- CUDA peak allocated: 15,478,553,600 bytes
- result: `QUALIFIED_EXECUTION`, 320/320 rows
- raw report SHA-256: `2f1c910e574a4637221ffbab2de572738582183673ba53c91fd733813151ada7`
- plan SHA-256: `d5c7d0e265e5dc08ee186aeab4d8ac185673975c75a9eb996541a3130292b4c7`

全 mechanical checks が true。両 model で同一 normalized hidden、native `torch.bfloat16` / diagnostic `torch.float32`、checkpoint/source 不変、random/unrelated control 整合、sham exact no-op を確認した。

## 主結果

事前固定した semantic / affected / horizon 4 / learned pair では、`full_route` が native の平均 `-0.046875`（1 positive / 3 negative）から FP32 の `+0.007673`（3 / 1）へ変わった。

`full - answer-boundary - non-boundary` の composition interaction は、native の平均 `-0.171875`（0 positive / 1 zero / 3 negative）から FP32 の `+0.008929`（3 / 0 / 1）まで縮小した。絶対平均で約 94.8% の減少である。`answer_boundary_only` は FP32 でも平均 `+0.006255`、`non_boundary_only` は `-0.007511` だった。

したがって、前回の強い負の合成 interaction は同じ final hidden の FP32 二択射影では維持されない。最終 readout arithmetic が、hidden 差を native BF16 answer-logit 格子へ写す際の主要な壁として局在した。ただし FP32 path は selected-row matmul でもあるため、「BF16 への最終 cast だけ」が原因とはまだ言わない。

4 cases のどの position lane でも intact/twin の離散回答は変わらず、native/FP32 間の予測差もなかった。また FP32 learned full route `+0.007673` に対し、Gram-matched random `-0.008833`、unrelated `-0.004844`、semantic unaffected full-route mean absolute `0.029226` だった。機構の局在はできたが、learned semantic signal の specificity は通っていない。

## 結論と次の gate

科学的 `winner` は引き続き `none`。支持されたのは、保存された final hidden 差と coarse native logit の間に、精度依存の readout bridge があるという局所機構までである。semantic memory、generalization、自然会話、capability、deployable precision policy は支持しない。

次は結果に依存せず事前固定した multi-turn harness を通す。元 model の query-only / inline と、workspace の full / answer-boundary / non-boundary を、固定履歴と各 lane 自身の回答を持ち越す自由履歴に分け、native BF16 と FP32 二択 readout の trajectory を比較する。生成結果は診断であり、失敗済み grouped F1–F5 を救済しない。
