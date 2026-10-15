# V13 — 正規化を含む workspace の状態設計

状態: **DESIGN_ONLY / 実験実装・学習は未開始**。2026-09-04。

機械可読の設計は [`DESIGN_CONTRACT.json`](../configs/v13/DESIGN_CONTRACT.json)。
これは実行用の `ExperimentConfig` ではない。設計検査の PASS は学習許可、計器修復、
科学的成功のいずれも意味しない。基点は V12 の
`fce1e8515b6344adefb9ef529939167371d5ba72`。既存コード・重み・過去の証拠は変更しない。

## 1. V13 の問いと V14 への境界

**同じ保存状態の、今読める部分と、次の状態遷移に効く部分を分離して測る。**

「二つの中間状態」は、独立した二つの記憶領域や直交した成分を仮定する言葉ではない。
同じ状態に対する二つの操作的な見方である。

- **R: 今の読取りに効く状態** — 状態を置換し、writer をさらに進めず、固定・適格化済みの
  query reader で読む。表現が区別できることと、回答を正しく変えることを分けて記録する。
- **D: その後の遷移に効く状態** — 同じ置換の後、固定した writer の残りの遷移を実行し、
  同じ reader で読む。read-now と、遷移を行わず状態を運ぶ carry-only を対照にする。

```text
同じ m_t への同じパッチ
  ├─ 直ちに固定 reader ─────────────────── 今の読取り効果 R
  ├─ 残りの writer 遷移 → 固定 reader ─── 後の読取りへの効果 D
  └─ 変換せず持ち越す → 固定 reader ───── 単なる持越しの対照
```

ここで「更新」は **activation の再帰的状態遷移**を指す。optimizer による重み更新とは
別物であり、V13 の一次実験中は base の重みを凍結する。

V13 は R-only / D-only / both / neither / UNKNOWN の範囲を同定する。
R と D を結ぶ学習済みの橋を作ったとは主張しない。V14 は、現在の reader と次の遷移への
入力を独立に操作し、特定の変換経路を復元・移植で検証する段階として予約する。
V13 で有意な効果が見つからなくても、十分な測定範囲と null 分布が得られれば有効な結果である。

## 2. 今回の設計に持ち越す事実と留保

| 区分 | 設計への反映 |
| --- | --- |
| V12 初期 no-op と更新所有権 | 過去の限定された工学的証拠として保持。更新後の内容依存を証明しない |
| V12 の BF16 logit 加算 | 小さい補正の forward 効果が丸め落ち得る。まず同じ捕捉テンソルの足し直しで調べる |
| reader 後の LN | `Head(LN(g * read))` では gate の共通倍率が通常ほぼ相殺される |
| writer の pre-norm 残差 | 生の状態は保存される。すべての大きさが全過程で消失するわけではない |
| V12 の深さ | writer=1、reader=1。反復の改善・悪化は未評価 |
| 既存 necessity | donor 正答率は paired flip ではない。F3/F4 だけの内容依存判定を継承しない |
| 既存データ | 隣接・端点の規則で解け、held-out の affected 被覆がない。V13 の一般化試験に転用しない |
| 既存自由生成 | base 本体だけの生成と、完全 wrapper のタスク読取りを区別する |

コード上の根拠は `engine.py` の Writer (3961–4093)、Reader (4096–4169)、
logit adapter (3858–3877)、sidecar 加算 (6064–6070)、necessity 指標 (5642–5653)。
V12 の後段加算問題で、別経路だった V10/V11 の失敗を一括説明しない。

会話内で行った保存重みの小規模診断は仮説の動機であり、V13 の封印済み実験 receipt ではない。
新規実験では改めて入力・重み・実行条件・結果を一組で記録する。過去の集計値の一致を
全件 logit の bitwise 一致と読み替えない。

## 3. 状態と正規化の契約

各 slot の **raw / pre-affine** 状態 `m` を次の座標に分ける。

```text
mu  = mean(m)
rho = sqrt(mean((m - mu)^2))
u   = (m - mu) / rho
m   = mu * ones + rho * u
```

`u` は平均 0・RMS 1 の形、`rho` は中心化した大きさ、`mu` は平均。
この分解に normalizer の epsilon を混ぜない。`LN_epsilon(m)` を形とすると、
そこに `rho / sqrt(rho^2 + epsilon)` が残り、大きさの交換を二重計上してしまう。
実際の LN は、再構成した状態から、元の epsilon / gamma / beta を用いて再計算する。
この座標では `LN(m) = gamma * [rho / sqrt(rho^2 + epsilon)] * u + beta` となり、
単位 RMS の形 `u` と実際の normalized state は同じものではない。

- `rho` が未凍結の閾値以下なら形は `DEGENERATE / UNKNOWN`。ゼロや donor の形を補完しない。
  対ごとの適格範囲を全セルで固定し、除外率と各層化での被覆を必ず報告する。
- 座標に「意味」「確信度」「重要度」を先に割り当てない。長さ・形式の代理変数かもしれない。
- 現行 LN は平均を厳密算術で除去する。半径は分散が epsilon より大きいと強く抑制されるが、
  完全消失とは限らない。ゼロ近傍では増幅が起こる。
- 現行の純粋な pre-norm writer と LN reader では、slot 内全成分への平均シフトは
  read-now / transition の双方で構造的 null。効果が出たら最初に丸め、乱数、介入位置を疑う。
- 半径は別で、残差状態と更新の比率を通じて後続の方向を変え得る。これを意味的な進展と
  呼ぶには、さらに donor 方向と非意味的な同振幅対照が必要。
- 全 slot tuple の同時並べ替えは reader の不変性対照。意味内容破壊とは数えない。

現在の `memory_effective_*` は、学習済み reader そのものではなく、診断用の非 affine LN を
使う。V13 ではこの値と **actual learned norm output** を別名・別フィールドにする。
全 norm の位置、axis、epsilon、gamma/beta hash、dtype、および steps / masks / projection を
architecture fingerprint に含める。テンソル形状だけの checkpoint 互換判定は禁止する。

## 4. 実験は五つの段階に分ける

| 段階 | 目的 | 次へ持ち越すもの |
| --- | --- | --- |
| S0 計器・タスク | 偽陽性、比較面、shortcut、証拠結合を修復 | 適格化済みの測定方法と新データ |
| S1 可視性 | どこで信号が消えるかを特定 | 各境界の paired trace と数値的な観測下限 |
| S2 座標 | 形・半径・平均の役割を分離 | 同一 checkpoint 内の 8 セル介入 |
| S3 遷移 | 今読む効果と後で読む効果を分離 | R / D の局在、carry-only 対照、UNKNOWN |
| S4 任意の枝 | workspace 条件付き変調 | 通常の adapter 効果と区別された局所的証拠 |

すべて未実装。S4 は primary に混ぜない。段階依存は測定可能性の依存であり、
前段の「意味的成功」を必ず要求するという意味ではない。局在した null も次の設計に使う。
全条件の巨大な直積や、同点 LR を選んで長く回す規則は作らない。

各段階で入力 lane を宣言する。保存済み V12 の **retained-inline diagnostic** は original
context を query/base に残すため、条件付き可読性・矛盾の上書きまでの主張とする。
**deferred primary** は query/base に original context を残さず、その同じ route で reader と
intact sufficiency を新たに適格化する。S2 は両 lane を別集計、S3 の一次主張は deferred のみ。
旧 inline checkpoint を接続し直しただけでは後者の適格化にならない。

### S0 — まず反証できる計器とタスク

**実行面。** 同じ token IDs / masks / labels / candidate IDs、padding、batch shape、
autocast、計算精度、attention backend、乱数条件で direct base / true bypass / zero route /
trained route を比較する。別 batch の評価は別の数値的頑健性試験。保存前後も同じ入力で比較する。
`hard_bypass` は adapter(0) を通すのではなく、補正経路を完全に切断する契約に直す。

**証拠。** source、要求 config と解決後 config の対応、base/workspace 内容、tokenizer、
prompt、data/split、runtime、per-case trace を hash で結合する。既存 ladder の真偽値だけを
信用せず、必要な測定本体から再計算する。欠落・空の出力は成功にしない。

**新データ。** 一次課題は内部ノード同士の非隣接比較。隣接 swap だけでは非隣接関係の正解を
変えられないため、内部の非隣接 transposition / block reorder を用いる。例えば:

```text
original: A > B > C > D > E > F
twin 1:   A > D > C > B > E > F
twin 2:   A > B > E > D > C > F
同じ query B > D ? は twin 1 で affected、twin 2 で unaffected。
B と D は全世界で内部ノード、距離 2、直接の辺ではない。
```

この小さな例の成立は列挙で確認したが、生成済み・適格化済みコーパスではない。
固定テンプレートにはしない。
original world と query を先に抽出し、その同じ world/query に対して affected / unaffected
の両方になる代替 edit を用意する。その後で両世界の適格性・構造層化を検査する。
これにより original context/query だけから affected を特定する抜け道を直接試験できる。

問い順・正解行列・名前・編集位置を固定しない。両方向を含め、両世界の hop を記録する。
同じ fact-position shuffle を twins に適用し、意味編集と提示順の変更を分ける。
held-out wording × affected status × hop の被覆を検査する。新しい名前への写像も別試験にする。
同じ original とその代替 edits は一つの world family として、split を跨がせない。

symbolic path oracle は正答でき、direct-edge/endpoint、query-position、memory-blind inversion、
query-only の shortcut 対照は一次課題を解けないことを、凍結する基準で確認する。
base inline の正の対照も新しい課題で再適格化する。旧 F1 の成功を転用しない。
全問同時正答を判定するなら、その同じ指標で正の対照を適格化する。
inline の適格化は課題の実行可能性までで、deferred route の sufficiency ではない。
後者は候補の訓練・評価後に因果的成功を主張する条件であり、未学習の query-only no-op が
chance を超えることを学習開始の条件にはしない。

**paired 指標。** affected 各件の元ラベルを `a`、donor ラベルを `b` とすると:

```text
L(M) = z_b(M) - z_a(M)
donor_gain = L(M_twin) - L(M_original)
```

FP32 で計算し、分布と固定・random・無関係 donor 対照との差を保存する。
「元に正答→donor に正答」「元に正答→元のまま」「元から donor に誤答→そのまま」
「元から donor に誤答→元へ戻る」の全遷移表を持つ。
望ましい遷移率は全 affected 件数と intact-correct 件数の**両方**を分母として報告する。
tie / invalid / abstention と除外件数を隠さない。

unaffected は prediction agreement、正→誤、誤→正、前後の GT accuracy、分布変化を分ける。
同じ誤答の維持を成功に数えず、誤答修正と破壊を混ぜない。identity と memory-blind predictor
には因果的 credit を与えない。F3/F4 のみの成功判定を禁止する。

不確実性の単位は paired-world family。両側・全 query・全 template・全介入を一緒に
resample し、同じ original に由来する代替 edits・名前写像・提示変更も同じ cluster に保つ。
訓練 seed のばらつきと別に報告する。選択用 development と封印 test を分離し、
数値閾値・区間・多重比較規則は独立 calibration の後、候補比較と test 開封の**前**に固定する。

### S1 — 捕捉した同じ値を使って、可視性を測る

raw slot → 実際の learned memory norm → projected K/V → query 別 read → gated update →
残差加算・減算で回収した delta → adapter → cast 前後の候補補正 → 最終候補 logits を記録する。

特に `(query + update) - query` の丸めと、最後の BF16 logit 加算の丸めを別々に測る。
全 forward を FP32 に替えた結果を、足し算だけの精度比較と呼ばない。
同じ捕捉 base logits / residual を BF16 と FP32 で再合成し、候補位置での ULP 比、
正確な差分、予測変化を記録する。gate は `g * Head(LN(read))` のように最終正規化より後で
効かせる比較とする。比較ごとの振幅・epsilon・dtype を凍結する。

前段で区別できる、K/V に届く、query が使う、logit が変わる、正しく donor に動く、を
それぞれ別の到達点として記録する。可視性だけで内容依存へ昇格させない。
既存の inline checkpoint を query-only に接続し直した失敗は分布変更であり、記憶欠如の証明ではない。

### S2 — 同一境界で 2 × 2 × 2 の座標交換

original=A / twin=B とし、`mu_c + rho_b * u_a` の `a,b,c ∈ {A,B}`、8 セルを両方向で比較する。
同じ checkpoint、query、mask、reader、gain、dtype を固定する。

slot 対応は同一 checkpoint の index 対応を主解析として全セル・全介入時点で固定する。
これは意味的に同じ slot だという仮定ではない。label を見ない対応付けは曖昧さを記録する
副解析のみとし、donor の全 tuple を同じ対応で動かす。full-tuple permutation null、
AAA/BBB の自己再構成、両側の直接 readout との一致を必須にする。

統計を渡す枝へ進む場合は、方向のみ vs 方向＋統計を比較し、constant / shuffled 統計を
同じ容量で用意する。近ゼロや OOD な hybrid による変化は意味的成功ではない。
読み手の LN 除去、writer 更新則、深さを一度に変えない。

### S3 — 読取り時介入と遷移時介入を分ける

候補 horizon は 1 / 2 / 4、reader はまず 1 step のまま。
各適格 checkpoint の中で、同じ step の同じ座標パッチについて:

1. 直ちに固定 reader で読む `read_now`。
2. 残りの writer 遷移を進めて読む `resume_remaining_transitions`。
3. 状態を変換せず運び、同じ reader で読む `carry_only`。

を比較する。未来の context、mask、乱数、重み、reader/gain は固定する。
正規化 topology を変える比較は同じ horizon の別実験にする。
1-step 学習重みを 4 回呼ぶだけの試験は「深さ外挿」。訓練済み 4-step の証拠にしない。
最終状態だけで学習した reader に途中状態を渡す OOD も明記し、そのまま能力の否定に使わない。

深さ間の比較では trainable parameter 数、処理データ、optimizer schedule、訓練・評価 FLOPs /
時間を報告する。一次推論は checkpoint 内の paired intervention とし、単なる多計算量の
利得や共通 gain の利得を「状態の深化」にしない。V13 は効果の分離と局在までとする。

### S4 — 任意の条件付き変調（別の枝）

既存 Mistral の native RMSNorm を交換せず、一つの事前指定サイトの出力 `n` に:

```text
n_prime = n + a * (delta_gamma(M, Q) * n + delta_beta(M, Q))
```

を加える候補。head の最後の出力だけゼロ初期化し、外側 `a` は固定した非ゼロの小さい値にする。
両方ゼロの積で学習入口を閉じない。M は query-independent writer から取得し、Q に回答 label
を入れない。一次 sufficiency lane の Q / base には元の world context を残さない。
inline lane は別に「矛盾する証拠の上書き」と表示する。

no-op、学習可能な静的変調、query-only、固定 carrier、memory-conditioned を比較し、
同等容量の通常サイトでの FiLM 的変調も対照にする。変調位置・特徴源・対象が K、V、残差の
どれかを固定する。局所的な変化が後段の norm で消えないことを最終 logits まで確認する。
同振幅の donor/fixed/random 対照を要求し、adapter の改善を workspace 内容の利用と混同しない。
S4 の存在は起動条件ではなく、この段階では配置・容量も未凍結である。
base 凍結でも変調サイトから loss までの逆伝播は必要になる。最終 logit にだけ補正を足す
V12 と同じメモリ・速度だとは仮定せず、起動前に activation と転送の予算を別途測る。

## 5. V14 に渡す「橋の探索用」記録

各 world/query/checkpoint/step について raw 状態、実際の norm 出力、形・半径・平均、
退化 mask、読取り・遷移・carry-only の出力、per-case logits、null 分布、全 provenance を渡す。
状態が大きすぎる場合は、事前固定した対象と不変な外部保存先・内容 hash を使う。
必要な状態そのものを保存せず、norm と hash だけで後から介入を再現できるとは言わない。

V14 の仮説は「遷移に効いた成分が、特定の変換を経て読める成分になるか」。例えば:

```text
早期の半径パッチ → 後続の形の変化 → K/V・read の変化 → donor 方向の回答変化
```

を検証する。ただし半径が唯一の橋であるとは仮定しない。
current reader と next transition の入力を original/twin で独立に交差し、現在の直通経路を
固定しても後の効果が残るかを見る。さらに候補となった後段成分だけを original に戻すと
効果が消えるか、その成分だけを移植すると再現するかを調べる。
全状態の置換で消えた場合は、局在した mediator の証拠より弱いと明記する。

probe の正答率、gradient alignment、二つの norm の相関、両方が変わった事実だけでは橋の証明にしない。
V14 の橋の学習・base 解放・14B への拡大はいずれもこの設計の範囲外。

## 6. 未確定項目と、実装へ渡す最小単位

未確定なのは、データ件数/seed/split hash、数値許容差、最小効果・sufficiency・retention の閾値、
cluster 区間と多重比較、gain grid、学習 schedule/予算/seed 数、途中 reader の適格化、任意変調の位置。
未確定値はゼロや既存 V12 閾値で埋めず、`PENDING_PREFLIGHT_FREEZE` / `null` とする。

次の実装単位は **S0 の反証 fixture と paired 計器 + S1 の読み取り専用 trace**。
その検査後に、新タスクと数値閾値を候補比較とは独立に固定する。
実行用契約はその時に別版として作成し、実装 hash・資源確認・実行判断を新たに必要とする。
この設計は training config を生成せず、remote job を起動せず、既存 run を変更しない。

設計ファイルの整合性のみを確認するコマンド:

```bash
python3 scripts/validate_v13_design_contract.py
python3 -m pytest -q tests/test_v13_design_contract.py
```

前者は過去の anchor、必須対照、段階依存、DESIGN_ONLY の境界を検査するだけ。
paired 指標・generator・介入の科学的正しさを実装検証した結果ではない。
設計 branch では engine の親 hash を維持する。将来の実装版は新しい実行契約で区別する。

## 7. 背景資料と、この設計固有の仮説

- [Ba et al., Layer Normalization (2016)](https://arxiv.org/html/1607.06450v1):
  正規化の不変性と再帰状態の安定化。ここから現在の read/transition の役割を再検討する。
- [Zhang & Sennrich, RMSNorm (2019)](https://arxiv.org/html/1910.07467v1):
  平均を除去しなくても共通倍率への不変性は残る。単純置換で gate 問題が直るとは仮定しない。
- [Xiong et al. (2020)](https://proceedings.mlr.press/v119/xiong20b.html):
  norm の配置と勾配挙動の関係。特定の placement が本課題で最良という根拠には転用しない。
- [Perez et al., FiLM (2018)](https://arxiv.org/html/1709.07871v2):
  条件付き affine 変調。効果が正規化直後に固有とは限らないため、配置対照を置く。
- [Peebles & Xie, DiT (2023)](https://arxiv.org/html/2212.09748v2):
  adaLN-Zero の先例。画像生成の結果を workspace の因果的成功や新規性の証明にしない。

V13 固有の仮説は「正規化の存在」ではなく、**状態のどの座標が、どの利用境界で、
何のために必要なのかを分離して測定すること**。V14 は、その測定で特定できた関係から設計する。
