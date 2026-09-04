# V13 S0/S1: retained-inline 可視性診断

2026-09-04。状態: **限定診断2本完了、新規学習なし、意味的成功は未成立**。

## 比較範囲

V12 task / semantic、各 seed43・16step の保存重み。Mistral-7B-Instruct-v0.3。
同一 eval の先頭2 world-pair records、各32 query-side cases、6 memory 条件。
原データは旧 V10 の隣接 swap 課題で、query/base に original context が残る。
条件付き可視性の診断であり、deferred sufficiency や新しい課題の能力試験ではない。
192 mode-case rows、再合成を含む1,152 paired observations が各枝にあるが、独立標本数ではない。

入力・実装・gain grid は実行前に固定。gain 1/4/16 は記述的比較のみ、選択や学習は行っていない。
実行元 commit は `45dd6faecda5d2b8e77dee49e1f2bfa6f07a14b1`。
GPU 実測は task 26.26秒、semantic 26.12秒の子プロセス。これは hash・load・保存込みの時間で、
モデル速度ベンチマークではない。詳細な入力/中間状態は炉の run に保存した。

## 観測

| 観測 | task | semantic |
| --- | ---: | ---: |
| intact の非ゼロ補正が通常加算後に残った cases | 0/32 | 0/32 |
| 同じ値の FP32 加算で補正が残った cases | 32/32 | 32/32 |
| intact 補正の最大絶対値 | 0.0153198242 | 0.0152587891 |
| intact 補正 / BF16 間隔の最大値 | 0.2451171875 | 0.244140625 |
| twin 対 intact の FP32 候補値が異なる cases | 23/32 | 30/32 |
| twin の望ましい反転 / 全 affected | 0/8 | 0/8 |
| twin の望ましい反転 / intact-correct affected | 0/6 | 0/6 |
| FP32 twin donor gain 平均 | 0.0000152588 | 0 |

全6条件で、全32 cases の補正は cast 後にも非ゼロ。しかし native 候補値は direct base と同じ。
この範囲では、主に最終加算時の丸めで観測可能な補正が失われたと切り分けられる。
FP32再合成は BF16 で計算済みの base/補正を足し直すだけで、全 forward の FP32化ではない。

FP32 twin gain の符号は task が正3/ゼロ3/負2、semantic が正4/負4。
小さい差の存在だけでは、内容に沿った因果的成功に昇格させられない。
gain 4/16を含む全再合成条件でも望ましい反転は0。32例の native intact accuracy は両枝27/32。

affected には「最初から donor に誤答し、そのまま」の2例がある。
これを donor 正答率だけで成功に数える旧計器の問題は、新 paired 計器で区別できた。
unaffected の native prediction agreement は24/24だが、正答は21/24で3例の誤答を維持している。
gain16では intact と swapped の双方で unaffected 正答が19/24になる。
これは同じgainの記憶交換による破壊ではなく、gain自体の baseline 劣化として分ける。

完全 bypass は direct base と候補単位で bitwise 一致する。
旧 `hard_bypass` は adapter(0) を通るため約1e-6の非ゼロ補正を残し、完全切断とは別物。
zero memory も同様に完全 bypass と同一視しない。

### LayerNorm・Reader の途中ではどうなっていたか

保存済み12テンソルファイルをhash確認後にCPUで再解析した。
`(q + update) - q` の相対 L2 誤差は task 0.4195%、semantic 0.4215%。
非ゼロ更新成分のうちゼロになった割合は0.3197% / 0.3891%、更新ベクトル全体の消失は両枝0/32。
twin交換後の差は実際の learned LN、K/V、read、adapter入力で各32/32行に残っていた。
交換前の `writer.raw_memory` は同一で、これは介入前を記録しているため期待どおり。

したがって、この標本では前段の加算・減算が更新を丸ごと消したわけではない。
また、LayerNormだけを除去すれば直る、という結論にもならない。
異なる表現境界の相対L2差を、そのまま意味情報の保持率・損失率には読み替えない。
詳細と計算式: [BOUNDARY_SUMMARY.json](BOUNDARY_SUMMARY.json)。

## S0 の限定反証 fixture

8 families / 16 pair records / 64 cases。symbolic path oracle は64/64。
direct-edge / endpoint 対照は全64件で棄権し、no fallbackでは32/64。
同じ original/query の代替 edit を family として保持する。
ただし同一fixtureへの query-text majority 当てはめは48/64で、shortcut-free corpus としては適格化していない。
これは小さな反証用 fixture の結果で、モデル性能・独立分割・訓練データ適格化の証拠ではない。

## 検証と次の境界

- 炉: 実行前216テスト通過、2診断とも exit0。checkpoint 全推論payloadの読込前後hash一致。
- 手元: 最終再実行は集計・棚卸し・境界解析も含む明示選択253テスト通過。
  最初の再実行はpackage探索path不足でcollection失敗し、`PYTHONPATH=src`を指定して通過した。
  実験失敗とは分け、呼び出しと結果を [VALIDATION.json](VALIDATION.json) に保存した。
- 2 trace / launch / execution / boundary summary の炉→手元の5ファイルhash一致。
- Engine・基盤モデル・workspace 重みは未変更。新しい訓練・14B化・V14橋の実装なし。

次は、見える加算と完全bypassを計器として実装し直し、新しい課題の正の対照を適格化する。
今回の32例から成功閾値を後付けせず、独立calibrationを置く。
LayerNormや深さを同時に変えず、S2/S3の座標・遷移介入は別の実行契約へ進める。

詳細集計: [task](TASK_SUMMARY.json) / [semantic](SEMANTIC_SUMMARY.json)。
機械可読の索引: [EVIDENCE_INDEX.json](EVIDENCE_INDEX.json)。

## 条件別の重み保存と棚卸し

手元V9の99ファイル、炉V10の140ファイル（重み・trainer等の状態）をhash化し、config/metricsなど2,532ファイルを別保存した。
重みの論理容量は手元20,404,398,065 bytes、炉22,246,879,694 bytes。
実際に解放できる容量は、hardlink/cloneなどがあり得るため未確定。
基盤モデル cache と他プロジェクトは対象外。
V11/V12 は別途、5つのrun rootにあるmanifest付き38 bundleをメタデータだけで確認した。
こちらの重み内容のhash化・コピーは行っていない。

ユーザーの訂正により **各条件の最新2 checkpointを残す** と確定。世代単位ではない。
条件・seed・独立実行を混ぜず、同一系列の最新2つの異なる保存stepを残す安全側の判定とした。
同じstepのfinal/checkpointは役割が異なり得るので、同一重みだと推定して削除しない。
確認範囲では最新2stepより古い対象がなく、**削除0件・容量解放0 bytes**。
これはプロジェクト全体の重複排除や容量整理の完了を意味しない。

V10にはcheckpoint4/checkpoint8/final8の3 bundleがあるが、保存stepは4と8の2つ。
V12のstep1/4/16は独立trialで、step1はbase_release_stepも異なるため、単純な保存履歴として統合しない。
古い重みのhashは復元可能なbackupではない。
保存方針と今回の範囲: [WEIGHT_RETENTION.md](../../../docs/WEIGHT_RETENTION.md)。
V11/V12の限定確認: [RETENTION_V11_V12_SCREEN.json](RETENTION_V11_V12_SCREEN.json)。
