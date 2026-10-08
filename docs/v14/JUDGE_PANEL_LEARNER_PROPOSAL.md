# V14：評価パネルから学習機へ戻すための設計案

2026-10-09。状態は **PROPOSED / NOT_TRAINED**。この文書は、保持中の重みを
次にどう調べ、どの条件を満たしたら学習機を変えるかを定める提案である。
新規学習・モデル更新・重み削除・追加生成の実行指示ではない。
judge panel の実測結果は末尾に分離する。Mistral は未実行である。

目標は、Latent Workspace を単なる出力の言い換え器にせず、
**不要な介入では base の質を保ち、有用な memory 内容がある時だけ、根拠のある変更を
引き出すこと**。出力差の大きさ、judge の好み、内容への因果的依存を別々に測る。

## 1. 現在の証拠が許す出発点

| 観測済みのこと | まだ言えないこと |
|---|---|
| 旧 semantic reader の train 16 世界 MI では、逆質問の差が reader 内で強く減衰した。slot 平均除去介入で平均絶対 answer-axis gap は 0.313439 → 0.011096。 | RMSNorm が原因、slot が全部崩壊、平均経路だけが学習失敗の原因、とは言えない。cap 再計算を含む介入であり、線形の媒介率ではない。 |
| centered 再学習後も、非一様 attention 経路の出力にほぼ質問によらない bias が残った。 | 平均を除けば質問依存になる、という保証はない。 |
| 自由文 48 比較では旧 V14 が 10 回答で変化。7 問に集中し、一般／関係で各 5 回答。 | 10 個の独立した成功でも、10 個の意味的 memory 利用でもない。 |
| centered intact/twin/unrelated/zero はそれぞれ base と 48/48 の回答 token 列が一致した。一方 intact は 2,828/2,973 token 位置、約 95.12% で native logits が変化した。 | 「BF16 で全部消えた」は誤り。選択された token が同じという有限バンク内の観測であり、一般的な非劣性証明でもない。 |
| 事後的な引用符修復を明示した補助評価では、旧 V14 を好む 2 組が同じ因果課題の greedy と sample211 に出た。sample211 は 80 語 → 54 語で 60 語制約も満たした。 | 独立した 2 課題の改善でも、一次判定の成功でも、内容因果性の証明でもない。旧 V14 の zero/unrelated/twin 対照がまだない。 |

一次 judge の無効・順序不一致は残す。補助評価を一次結果へ混ぜない。
一般課題は 8 task、関係課題は 4 world の順逆で、構造上の評価単位は計 12。
seed 違い、順逆、A/B 順序、judge 人数を独立 task 数として数えない。

出典：
[MI と一変数再学習](../../provenance/pilots/v14_mech_repair_20261009/README.md)、
[自由文・一次評価・補助評価](../../provenance/pilots/v14_answer_bank_20261009/README.md)、
[機械可読集計](../../provenance/pilots/v14_answer_bank_20261009/SUMMARY.json)。

## 2. コードから見た現在の不足

1. [PrecisionAwareWorkspaceBridge.read_delta](../../src/latent_workspace_ft_v10/precision_bridge.py)
   は最後の正規化済み hidden state を query にする。writer は query-independent だが、
   reader が質問内の役割や逆向きを保持できるとは限らない。
2. [CenteredValueWorkspaceBridge.read_delta](../../src/latent_workspace_ft_v10/contrastive_read_bridge.py)
   は normalized memory の V だけを centering する。Q/K は旧経路のままであり、
   constant で非一様な attention を禁止する構造にはなっていない。
3. [objective / train_cell](../../scripts/run_v14_precision_bridge.py) はすでに
   paired CE、affected donor hinge、unaffected stability、unrelated gap、residual penalty を持つ。
   ただし supervision は FP32 の **2 candidate 行**に限られる。
   新たに「対照損失」と名付けるだけでは既存の失敗原因を解決しない。
4. [centered train_cell](../../scripts/run_v14_centered_bridge.py) には query projection と
   attention Q の gradient norm があるが、損失項ごとの勾配方向・相殺までは分解していない。
   [capture_reverse_panel](../../src/latent_workspace_ft_v10/bridge_reader_panel.py) は
   production Q/K/V を観測できる。新 reader に旧 `trace_reader` の V 仮定を流用しない。
5. [native_full_readout / generate_group](../../src/latent_workspace_ft_v10/answer_bank_generation.py)
   は full-sequence・full-vocabulary の native head と全 prefix 再計算を固定している。
   [FrozenBackend / ordinary_base_gate](../../scripts/run_v14_answer_bank.py) の
   decoder 読み出しは Mistral 固有。これは一般モデル用 interface の完成ではない。

## 3. 学習より先に通す：保持重みの内容因果性ゲート

### G0：実装の同一性を再固定する

旧 semantic step256 と元 base を固定し、source / plan / tokenizer / checkpoint hash、
native full-head geometry、同一 prompt、同一 token-ID CDF 乱数を束ねる。
zero は source text を空にするのでなく、**書き込み済み memory をゼロ**にする。
base と zero の全 logit・生成 token 一致を要求する。既存の古い artifact は更新しない。
通常 base forward、zero gate、保存重み hash のいずれかが失敗したら停止する。

### G1：良い例だけでなく、全変更例と未変更対照を調べる

無学習で `base / legacy intact / legacy zero / legacy unrelated / legacy twin /
legacy norm-matched random` を比較する。第一の開発パネルは、既存バンクの
**変更 10 組すべて**を含める。因果課題の 2 組だけに絞らない。
同じ lane・regime の未変更対照も残す。選択裁量をなくす小さな案は、既存の未変更 38 組を
すべて含む、元の 48 case-regime 全体の再計測である。
旧バンクで結果を見た集合なので、これを新しい未見 holdout とは呼ばない。

別に、task type・言語・制約の強さを対応させた未使用の world/task 集合を、
生成を見る前に固定する。新しい集合では結果が「未変更」になることを選定条件にしない。
期待する preservation 条件を事前にラベルし、実際には変わった例も捨てない。
旧 48 組の開発パネルと新 holdout は別表で集計する。

対照の意味も固定する。

- unrelated は task に必要な事実を含まない別内容。writer は query/reference を見ない。
- twin は最小の事実変更。関係課題では正答が変わる affected と変わらない unaffected を持つ。
  一般課題で user prompt の事実が authoritative な時は、矛盾する memory に追従することを
  成功にしない。現在の causal 課題の「9→6」と twin の「9→12」がこの区別に当たる。
- norm-matched random は、事前固定 seed による query-independent な random slots を
  **同じ mask と各 active slot の書き込み後 L2 norm**に合わせる案とする。
  同じ case の各生成条件で同じ realization を使う。normalization 後の共分散、
  residual norm、native logit 差まで一致する対照ではない。これらは別に実測する。
  単一 random realization の偶然一致から一般的な内容非依存性を断言しない。

主要な問いは「文章が違うか」でなく、次の二つを同時に満たせるかである。

1. 元／twin の事実変更に対応した根拠・回答の変化があり、unaffected は壊さないか。
2. 一般課題の有用な変更が intact 内容に依存し、unrelated/random でも同様に出る
   generic perturbation や、user facts の上書きではないか。

free generation の分岐後だけを比較せず、base の固定 continuation を全条件へ与える
matched-prefix panel を併記する。そこで full-vocabulary 差、donor 方向、必要事実の
整合性を測る。これは KV cache を持ち越す実験ではない。
norm-matched memory で residual 振幅が一致しない場合、振幅との交絡を `UNRESOLVED` とし、
必要なら別の事前固定 residual-norm 対照を設計する。結果を見て gain を合わせない。

### G2：学習設計へ進める結果と、進めない結果

| 無学習パネルの結果 | 次に許す判断 |
|---|---|
| intact に固有の有用性と、事実に対応した変更が新 holdout にも見える | selective reader/gate の候補を、小さな train-only 比較へ進める。まだ winner ではない。 |
| 良い変更が unrelated/random でも同程度に出る、または結果が不確定 | generic readout perturbation の可能性を残す。内容利用を目標に Q–memory 相互作用の train-only 診断へ戻る。現在の変更を意味学習の成功と呼ばない。 |
| correctness・制約遵守・grounding の明確な劣化が生じる | 振幅拡大・長期 run を止め、preservation の失敗を先に解析する。 |
| 実装 gate／対照／必要な judge 観測が欠ける | `BLOCKED` または `UNKNOWN`。欠測を勝敗や tie へ変換しない。 |

有意差の閾値や非劣性 margin は、この小さな開発パネルを見て選ばない。
一般的な「base を割らない」を検定したい段階で、独立 world/task を単位とする規模と
許容差を別に事前登録する。有限例の同一回答は、そのまま有限例の同一回答として残す。

## 4. 条件付きの学習機変更案

### 4.1 モデル依存の演算を native readout binding に閉じ込める

既存の [FunctionalBoundaryAdapter / BoundaryDescriptor](../../src/latent_workspace_ft_v10/model_binding.py)
と [可搬境界の契約](../V14_PORTABLE_BOUNDARIES.md) を土台にする。
`MistralPrecisionBridgeAdapter` を削って generic と名付けるだけにはしない。
次の責務を持つ **functional interface の追加案**とする（未実装）。

```text
encode_memory(ids, mask, boundary) -> context_features, boundary_receipt
encode_query_prefix(ids, mask) -> native_query_state, query_token_features
read_native(native_query_state, fp32_delta) -> full_logits, applied_delta, arithmetic_receipt
describe_readout() -> norm_phase, head_geometry, dtype_policy, cache_policy, support_status
```

native norm の種類・位置、head bias/tie/scale、mask/position、BF16 cast の順序、
全 sequence GEMM の形状は model binding 側が所有する。workspace は tensor と mask だけを
受け、model type の分岐や正答 token ID を所有しない。
native path と FP32 診断 path を名前付きで分離し、未対応構造は fail closed にする。
descriptor の存在を数値等価性と呼ばず、各モデルごとに zero/native parity を測る。
まず現在の Mistral で既存 receipt を再現し、他モデルは別 canary にする。

### 4.2 query 表現を変える前に、損失の相殺を測る

同一 world の順質問・逆質問・intact/twin を同じ minibatch に入れ、
CE/donor/stability/unrelated/preservation 各項について Q/K/V/up/writer の
gradient norm と内積・cosine、更新前後の donor margin を train-only に記録する。
小 norm の cosine だけを大きな効果と解釈しない。

比較は最初に一つだけ変える。例えば、既存の最後の answer-position query と、
user-query token span からの固定 pooling query を比較する。
pool の対象は prompt token から決まり、reference の entity-role annotation や正答は
推論入力へ入れない。hidden width を維持する pool なら既存 projection を使えるが、
分布変更にはなるため別 learner condition として初期値・予算・parameter 数を記録する。
役割を持つ二つの query stream などの大きな設計は、この最小比較の後に置く。

train の reciprocal-query 小課題でも方向が分かれないなら、long run/base full update
へは広げない。分かれる場合でも、それは overfit 成立であって汎化ではない。

### 4.3 preservation と内容条件付きの有用性を別の損失にする

現行の二値 answer gap に対する unrelated penalty だけでは、自由文の語彙全体、
文字数、説明の捏造を守る制約になっていない。以下は **損失候補**であり、
係数や新しい正解データはまだ固定していない。

| 損失／検査候補 | 適用対象と目的 | 必要な対照 |
|---|---|---|
| full-vocabulary base-preservation KL | 不要・無関係な memory の固定 continuation 位置で、凍結 base 分布からの不要な逸脱を抑える | zero/irrelevant、全語彙の正規化、同一 prefix。全ケースに無差別適用して有用な変化まで消さない。 |
| content-contrastive directional term | 関連 memory の original/twin と query reversal に応じて、ground-truth に対応する readout 差を要求する | affected/unaffected、同じ batch、memory norm/random 対照。現行 donor hinge を追加名だけで再発明しない。 |
| grounded response supervision | train 専用の独立に作成・検証した説明 target で、根拠・不確実性・具体的な次の検証案を学ぶ | fact consistency、語数／文数／JSON等の独立 checker。今回の judge が好んだ文章を正解として取り込まない。 |
| selective intervention gate | query と memory の関係から介入の要否を学び、不要な変更を抑える | gate 値だけでなく preservation と donor 方向を測る。全閉じで base を複製する解も、全開で常時 bias を出す解も区別する。 |

概念上は `delta_effective = gate(query, memory) * delta_content(query, memory)` とできるが、
gate は「confidence」や「意味理解」の測定器ではない。
零初期化を重ねて gate と reader の両方に勾配が流れなくなる設計を避け、
step 0 の native zero 同値と、必要な upstream gradient の到達を別々に試験する。
gate の追加、query pooling、損失変更を一つの cell に同時投入しない。

FP32 の訓練損失と native BF16 の生成は同じ計算ではない。
native の可視性は評価軸として残し、通すための gain sweep や tolerance 拡大は行わない。
今回 centered の logits は多くの位置で変化しているため、単純な振幅不足だけを
改良目標にする根拠はない。cap を上げるだけの案は優先しない。

## 5. データ・judge・公開 artifact の境界

- 現バンク・既存の 64-world holdout・その judge 文はすべて閲覧済みの開発資料。
  次の確認実験で「未見」に戻さない。
- 学習 target、development 選択、最終 holdout を world/task と paraphrase family ごとに分ける。
  同じ world の逆質問や sampling seed だけを別 split にしない。
- judge の選好を使う preference training は別の提案・別データ契約とする。
  今回の 10 変更組、補助修復ラベル、将来の panel verdict を、そのまま DPO 等へ流さない。
- multi-judge は観測者の違いを調べる追加資料。Mistral 系 judge は被評価モデルと同系統の
  ため、独立した真値参照と見なさない。他系列でも独立性や正しさが保証されるわけではない。
  モデル別、A/B 順序別、invalid/refusal/missing、引用の整合性を残し、多数決で欠測を消さない。
- 文字数、文数、JSON構文、visible facts との矛盾は可能な範囲で別に検査する。
  judge の自信や長い説明を、これらの検査の代わりにしない。
- 人間用の blind sheet は judge 出力と別管理。人間が未評価なら `PENDING` のままにする。

## 6. review / 実装 / 実行の分け方

この proposal の PR で許す主張は設計・コード対応・証拠の整理・追加 judge 観察まで。
PR の承認は、新学習や追加 API 呼び出しの実行 receipt を意味しない。

次の実装を依頼された時の最小単位は、(a)保持重みの legacy memory-control assay、
(b)モデル固有の readout binding と parity tests、(c)train-only gradient 分解、の順とする。
gate/損失/query 表現の新 learner は G1/G2 の結果を受けて一つずつ設計・凍結する。
各実験は予定分母、source/model/runtime/seed/hash、時間・call/token budget、停止条件、
重みの保存対象を事前に固定する。失敗時は記録を残し、別 plan で再試行する。

`IMPLEMENTED`、`TESTED`、`QUALIFIED_EXECUTION`、`CONTENT_EFFECT_OBSERVED`、
`QUALITY_PRESERVATION_OBSERVED_ON_PANEL` は別の段階である。
後二者も普遍的な意味理解・知能増幅・非劣性を意味せず、対象集合を必ず併記する。
どの gate が欠けていても `winner: none` と `semantic_promotion: false` を保つ。

## 7. 追加 judge panel：OpenAI 完了、Mistral 未実行

設計の初稿は判定前に作成し、この節だけ実測後に追記した。
状態は `VERIFIED_PARTIAL_RECEIPTS_NOT_GOLD`。他系列間の比較はまだできていない。

凍結済みの [selection.json](../../data/v14_judge_panel/selection.json) は、既存の変更 10 組すべてと
固定の同文校正 4 組、計 14 組を束ねる。
selection SHA-256 は `4eaeec699552b9ef28fe785c574ac76140e7a7668b31f2d0ce69b7d18788df94`。
旧 judge の verdict は入力へ渡さない。
これは新たな生成 holdout ではなく、同じ文章への評価者間比較である。

`gpt-5.4-2026-03-05`（Responses、reasoning low）は 140/140 応答、厳密有効 140/140。
10 変更組の各 5 反復を AB/BA 両順序で評価したところ、全反復で安定した workspace 選好は
2 組（同一因果課題の greedy / sample211）、tie は 3 組、残る 5 組に順序不一致があった。
同文校正 4 組はすべて全反復 tie。140 票は独立した 140 課題・評価者ではない。
`mistral-large-4` はキー未確認のため 0/140。人間評価も `PENDING` のままである。

この結果は「検証案の具体化」という保持したい変化の候補を強めたが、G1 の省略理由には
ならない。良く見えたのは legacy 側で、対応する内容対照はまだない。
greedy は両方 60 語制約を超え、sample211 のみ 80→54 語で制約内になった。
workspace の実験案にも無作為化や未介入群の明示がない。
さらに judge 自身が、別の関係課題で 33/30 語や 29/32 語の差を誤って説明した。
ゆえに厳密な引用・JSON 通過を推論内容の正しさと見なさず、語数・形式・事実整合は
独立の検査として残す。事後語数検査で judge の票や選択組は変更していない。

**今回の設計判断：新損失を直ちに積み増すのでなく、G0/G1 の legacy 内容対照を次の
最小実装にする。** native binding、train-only 勾配分解、その後の一変数 learner 比較という
順序は維持する。base 保持も既知の base の誤りを無差別に固定する意味ではない。

[結果と限界](../../provenance/pilots/v14_judge_panel_20261009/README.md)、
[全回答・全反復の読解パネル](../../provenance/pilots/v14_judge_panel_20261009/analysis/PANEL_REVIEW.md)、
[再構築可能な集計](../../provenance/pilots/v14_judge_panel_20261009/analysis/SUMMARY.json)。
実行 source は `29af1074af380660d728e3221e400558e3e0cc79`。
この設計に基づく新学習、内容因果性の実証、非劣性の成立はいずれも未実施／未確立である。
