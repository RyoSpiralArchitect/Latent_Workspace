# V14 constrained multi-turn choice assay

2026-09-13 に SpiralReality-furnace の RTX 5090 で、precision gate の次に固定した multi-turn harness を実行した。4 world/side scenarios × 14 conditions × 2 history modes × greedy+3 matched samples × 2 readouts = 896 trajectories、各4 turn、合計3,584 answer turns である。

候補tokenは `no` / `yes` の二択に固定した。これは自然文chatではなく、微小なworkspace差が複数turnの状態遷移で可視化されるかを切るための constrained generation である。task / semantic checkpoint の full-route、answer-boundary-only、non-boundary-only を intact/twin で全て残し、元のbase modelも query-only と inline-context の両方で比較した。

## 二つの履歴

- `teacher_forced_fixed_history`: 各branchの生成結果は記録するが、次の質問前には全conditionで同じoriginal-side answer tokenを追加する。
- `free_history`: 各condition / readout / sampling branch自身が生成したanswer tokenを次の質問へ戻す。

質問順は affected q0 → unaffected q2 → affected q0 → unaffected q2。各turnはfull-prefixを再計算し、KV cacheは使っていない。したがって履歴を介した再帰は測れるが、KV-cache固有のclaimはしない。sample乱数はseed / scenario / turnだけで決め、condition・history・readout間で同じuniformを使った。

## 実行と整合性

- source commit: `992c0bb14e4daa90faba8a904af2505960eb0cd9`
- runtime: 74.843 seconds
- CUDA peak allocated: 14,899,510,784 bytes
- result: `QUALIFIED_EXECUTION`, 896/896 trajectories, 3,584/3,584 turns
- raw report SHA-256: `19b0a0305b2ab014f48552b0d325a34576a7c8f846473c6da11d435de0972807`
- plan SHA-256: `a8e70b61ab01458d872632ecea23251df84c363750d9bbbab02f5fb1caabce17`

全 mechanical checks が true。同じprefixを再計算したnative/FP32 branchesはdual readout値をexact再現し、固定履歴はoriginal answerだけ、自由履歴は各branchの生成answerだけを追加した。turn 0のtask / semantic × 3 routes × 2 readouts = 12平均値はprecision predecessorと全てexact一致した。

## semantic trajectory の主結果

`full_route` は固定履歴・自由履歴、native・FP32の全4条件で intact/twin trajectory change が `0/16`。affected answer changeも0だった。

`answer_boundary_only` は固定履歴で両headとも `0/16`、自由履歴で両headとも `1/16`。`non_boundary_only` は固定履歴で両headとも `0/16`、自由履歴でnative `0/16`、FP32 `1/16`だった。しかし全semantic cellsを合わせても affected turnの intact/twin answer change は0である。greedy trajectoryも全route / history / headで intact と twin が一致した。

固定履歴FP32のsigned pair effectは、full-routeで turn 0→3 が `+0.009081, +0.013380, +0.002933, +0.007402`。単調増幅ではない。boundaryは `-0.009676, -0.004045, -0.018144, +0.008085`、non-boundaryは `-0.022518, -0.001300, +0.010918, -0.008891` で、donor方向も維持しない。

## 遅延分岐の正体

semanticの二つの遅延分岐はどちらも `w0_s0 / sample_213` だった。boundaryではnative/FP32とも、intact `no, no, no, no` に対し twin `no, yes, no, yes`。non-boundary FP32も同じ分岐だった。

最初の差はturn 1のunaffected質問で起きた。その時点のprefixはintact/twinで同一。その小さなscore差がmatched samplingの閾値を跨ぎ、異なるanswer tokenが履歴に入り、turn 3ではprefix自体が異なって大きく分岐した。これは「微小差→履歴再注入→後段増幅」の機械的実例だが、affected donor方向のsemantic accumulationではない。

さらに fixed/free trajectoryはbase inlineで両head `6/16`、base query-onlyでnative `13/16`、FP32 `12/16`が変わった。semantic各conditionも `12–13/16`。履歴自己再注入はworkspaceなしでも強く、自由履歴の発散だけをsemantic evidenceにできないことが明確になった。

## 生成の手触り

全regime・全turnをまとめたFP32 target accuracyは、固定履歴でbase inline `0.890625`、base query-only `0.75`。semantic intactはfull `0.703125`、boundary/non-boundary `0.71875`。twin targetはfull `0.515625`、boundary/non-boundary `0.5`で、counterfactual contextへ追随しなかった。

自由履歴ではbase inline `0.71875`に対し、semantic intactはfull `0.4375`、boundary `0.40625`、non-boundary `0.46875`。自分の誤回答を履歴へ戻すと、semantic差より一般的な履歴誤差が先に増幅した。

## 結論

科学的 `winner` は引き続き `none`。今回支持されたのは、小さな同一prefix差がsample閾値を跨いだ後に履歴を通じて増幅され得ることまで。一方、semantic checkpointのaffected intact→twin answerは一度も変わらず、donor-directed temporal accumulationは支持されない。

次は会話を長くする前に、モデル依存adapter側へprecision-aware comparison bridgeを置き、donor-directed marginをunaffected/unrelated controlsと同時に学習または校正するのが最小手である。その後、今回と同一の4-turn harnessを再実行する。現状でhorizonだけ伸ばすと、semantic signalよりgeneric history errorを速く増幅する。
