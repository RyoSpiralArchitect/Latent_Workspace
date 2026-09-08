# V14 answer-boundary recurrence microscope

2026-09-08 に、完了済みの Mistral-7B task / semantic checkpoint を読み取り専用で比較した。全セルは同じ token 履歴を使い、8 cases × 4 controls × 5 answer boundaries × 2 models = 320 rows を一度だけ実行した。学習、自由生成、weight の書き込み・削除は行っていない。

## 何を分けたか

1. affected query の `twin donor margin - intact donor margin` と、unaffected query の original-margin stability
2. layer 16 の更新が raw unembedding direction と、上位 16 layers を通した local answer-gradient direction のどちらへ向くか
3. requested update、native BF16 add、layer-16 input RMSNorm 前後の可視性
4. one-shot read、毎 turn の no-cache read、one-shot K/V carry、毎 turn read + K/V carry、base-history reset control

回答 token と次の同一 query は強制し、全条件で履歴を固定した。cache lane は、学習済み reader が full-prefix 計算で作った current-token update を native layer-16 pulse として再生する hybrid diagnostic であり、serving integration ではない。

## 結果

- horizon 0 の affected 4 cases は両 checkpoint とも全 read lane で signed pair effect = 0、prediction change = 0。
- しかし local answer-gradient への learned-pair projection は task `+0.003139`、semantic `+0.003184` で、各 4/4 cases が donor 向きだった。observed BF16 answer-margin shift は 0 のまま。
- 更新 RMS は約 `0.00187–0.00194`。native BF16 add で消えた成分は約 `6.5–7.0%`、median directional size は約 `4.3–4.4 ULP`。RMSNorm 後の差は約 `0.062–0.064 RMS`。従って主な壁は RMSNorm による消失ではなく、その後の answer-axis alignment と coarse logit readout にある。
- semantic の isolated repeated last-token lane は horizon 4 で affected mean `+0.078125`、3 positive / 1 zero。ただし complete reader route は `-0.046875`、1 positive / 3 negativeへ反転した。
- semantic の repeated K/V-history contrast は horizon 4 で全 4 cases が 0、trajectory AUC mean `-0.015625`。task も donor 向きではない。K/V-mediated semantic amplification は支持されなかった。
- Gram-matched random と unrelated-family control も同じ粗い logit 刻みで動き、unaffected rows にも変化がある。specificity gate は通らない。

したがって科学的な `winner` は引き続き `none`。今回見えた芽は「semantic cell の last-token component」だが、現行の all-position reader composition がその成分を相殺または反転している。次の最小 gate は K/V carry の強化ではなく、position-selective / answer-axis-aware な route composition の切り分けになる。

## Mechanical recovery

raw run は `BLOCKED_EXECUTION` のまま保存した。唯一の false check は、full-turn call と final-token split call の sham cache が bitwise identical であることを要求した点だった。BF16 SDPA は chunking が違うと数値経路も変わるため、この cross-chunking equality は不正な invariant である。

独立 verifier は raw report を変更せず、同じ chunking lane 内で sham intact/twin が exactly equal、signed pair/history contrast が全て 0、その他の mechanical checks が全て true であることを確認した。これにより mechanical execution のみ `QUALIFIED_VERIFIER_RECOVERY`。科学値の再計算・選択、target model の再実行、semantic promotion はしていない。

## Claim boundary

この pilot は、固定された 8 cases における局所投影、native arithmetic visibility、repeated read、K/V-history mediationを切り分ける記述的診断である。失敗済み grouped F1–F5 gate を救済せず、semantic memory、generalization、natural chat accumulation、capability、speed を立証しない。
