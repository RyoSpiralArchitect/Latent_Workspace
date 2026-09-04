# V13: 最初の計器・可視性診断

2026-09-04。ユーザーの炉実行依頼に基づく、学習を伴わない限定診断。
元の `DESIGN_CONTRACT.json` と V12 engine は変更しない。
実行範囲は [`VISIBILITY_RUN_PLAN.json`](../configs/v13/VISIBILITY_RUN_PLAN.json) に分離した。

## 今回行うこと

- S0 の paired 計器: 元の正答から donor 正答への遷移を、最初から donor に誤答した例と区別。
  同点は分類判定 UNKNOWN、有限な連続 margin は独立に保存する。
- S0 の反証 fixture: 8 families の同じ original/query に affected/unaffected の別 edit。
  symbolic oracle・単純 shortcut を検査する。完全な生成器・独立 test corpus の適格化ではない。
- S1: V12 task/semantic の seed43・16step 保存重みを各1本、既存 eval 先頭2ペアで比較する。
  各ペアの両側・全 query、6 memory 条件、同一捕捉値の native/BF16/FP32 再合成を記録する。
  gain 1/4/16 は記述的な可視性確認のみで、最良 gain の選択には使わない。
- 完全 bypass は直接 base と同じ入力で比較する。adapter(0) を残す旧 `hard_bypass`、
  zero memory、完全 bypass は別の条件として保存する。

## 証拠と上限

実行前の実装・plan・eval・checkpoint manifest/workspace hash を結合する。
各 checkpoint の全推論 payload は読込前後に hash を確認する。
入力 IDs/mask/labels/candidates と限定範囲の中間テンソルは炉に保存する。
全 query の候補 logits と trace を残すが、全系列の記録は先頭2 query に制限する。
CPU threads は2、GPUの既存 compute client があれば起動しない。
記録用 hook が出力を変更しないことと、実際の reader 出力・native 再合成との一致を検査する。

この診断は **retained-inline lane**。古い課題を用いるため、deferred sufficiency、内容依存、
一般化、V14 の橋の発見は主張しない。S0 全体が適格化されたとも主張しない。
新しい hard task・閾値・訓練条件は未凍結であり、今回の出力から test 閾値を後付けしない。

## 実行

```bash
python scripts/execute_v13_visibility.py --output-dir runs/v13/NEW_RUN_ID
```

このコマンドは plan に記載した炉の既存 checkpoint を読み取り、別の出力先へだけ書く。
既存ディレクトリの上書き・optimizer 起動・weight pruning は行わない。
`--preflight-only` は入力結合・fixture までで、GPU 空きや実行成功の証明ではない。
`EXECUTION.json` の子プロセス完了と、実際の診断結果は区別する。

## 重み保存

ユーザーは旧重みの記録後削除と「最新と1個前」の保存を依頼した。
世代単位か各条件の checkpoint 単位かを確認中。V12 の今回の読込対象は保護する。
削除用の台帳を別途作り、今回の診断から暗黙に削除しない。
hash・config・metrics は重みの復元可能なバックアップではない。
