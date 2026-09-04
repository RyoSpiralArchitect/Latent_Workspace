# V14: モデル境界とworkspace演算の分離

## 現在の位置づけ

V14の最初の成果物は、モデル固有の実行境界、workspaceの演算、正規化、
最終logit加算、観測処理を分けた実装基盤である。
「現在読める状態」と「後続更新へ効く状態」の橋渡しを発見したという結果ではない。
この文書と `configs/v14/PORTABILITY_RUN_PLAN.json` は実モデルのGPUチェックより前に
コミットする。実行結果、最終テスト集計、使用commitは実際のreceiptで記録する。
計画ファイルや小規模テストを実モデルの成功receiptとして扱わない。

実行前のローカル全テスト結果は741 passed、CUDA専用3 skipped、25.33秒。
これはFurnace上の実モデル実行結果ではなく、CUDA-onlyのskipを成功として数えない。
この計画の固定source anchorは次のとおり。commitとplan自体のhashは、実行前のlaunch receiptで束ねる。

| 対象 | SHA-256 |
| --- | --- |
| package直下全Python実装のfingerprint | `dfb0279a86de0758ed3a23a046f9daba3f6f2f835766bc3159a14a710e5118d1` |
| `engine.py` 単体 | `3e7659b7c927cab23b4d994ce2e320d99431e4ba657d560c1094bc36de596178` |
| `run_v14_portability_canary.py` | `5b225593f3fef729133d14f95d83320ae8cb32100b0801c1410a8d3e007d26c4` |

実行前にいずれかが異なればモデルをロードせず停止する。結果を見てからpinを更新しない。

## 実装した責務の分離

| モジュール | 所有するもの | 所有しないもの |
| --- | --- | --- |
| `model_binding.py` | native decoderのcut、encode/decode、境界記述 | workspaceの正規化・反復・学習目的 |
| `workspace_core.py` | functional writer/reader、低ランクlogit adapter、ReaderState | モデル固有のRoPE・mask・decoder配置 |
| `normalization.py` | workspace演算子の明示選択、既知native normの記述 | native backbone normの置換、未知normの推測 |
| `numerics.py` | 計算済みbase/residual logitsの最終加算 | backboneやreader全体の精度設定 |
| `observability.py` | 名前を指定したnorm呼び出しの有界な入出力観測 | attention重み・KV全体の観測、因果的有用性の判定 |
| `implementation_identity.py` | package直下の全Python実装ファイルのfingerprint | モデル重み、全依存ライブラリ、再帰的な全repositoryの同一性 |

`engine.py` は互換import名を再公開し、既存の学習・評価経路へこれらを接続する。
`FunctionalBoundaryAdapter` のnative対応はGPT-2、Mistral、OLMo2。
完全なcustom split protocolは、そのモデルが提供する意味に委譲する。
GPT-2に似た構造の認識や境界descriptorは、未知モデルの動作保証ではない。
Mistral/OLMo2は対応Transformers版と配置を検査し、未知のAPIを黙って受け入れない。

native cut `N` はN個のdecoder blockを通過した残差状態を指す。
最終cutでもnative最終normより前であり、decode側がそのnormとheadを実行する。
今回のインターフェースはcacheを使わず、外部から任意position IDsを渡す経路や
attention出力を返す経路ではない。境界descriptorのhashは記述の同一性であり、
重みのhashやnative/split一致の測定結果ではない。

## 既定動作の保存と、明示的な変更

既定値は `workspace_norm_kind=layer_norm`、`workspace_norm_eps=1e-5`、
`logit_composition=legacy_native`。抽出した部品のparameter名と演算順序を保存する。
`tests/test_v14_legacy_parity.py` はsealed commit
`ed5ce398e08b55d3118a316cfda61e36b8cc4b54` のengineをGitからメモリ上へ読み、
固定シード初期値・state_dict・RNG・出力・入力/parameter勾配・norm/gate呼び出しを
小さなCPUケースで完全比較する。writerの各mode、readerの1/2反復、zero/open head、
FP32/BF16 CPU autocast、tiny Mistralのinline/sidecar/deferred経路と反事実・安定性損失が対象。
これはその固定ケースでの互換性であり、全モデル・全kernel・旧optimizer再開の証明ではない。

workspaceをRMSNormへ変える操作は、平均を除くかどうか、parameter構成、勾配を変える
**アルゴリズム変更**である。可搬化のための無害な整形とは扱わない。
設定対象は構築されるfunctional writer/reader/sidecarのnormであり、native backbone normや
全ての正規化呼び出しを一括置換しない。例えば既存のfixed-carrier生成式の
`F.layer_norm` は従来のままである。

`legacy_native` は `base + residual.to(base.dtype)`。
`fp32_accumulate` は `base.float() + residual.float()` を計算し、結果をFP32のまま保つ。
後者は**最終加算だけ**の精度変更で、BF16 forward中や状態差の回収時に既に失われた情報を
復元しない。true bypassは元のbase tensorとdtypeをそのまま返す。
nonlegacy加算はenabledなinline-sidecarに限定される。

`ReaderState` は初期状態、最終状態、各反復で足す更新、gate/read統計を区別する。
`final - initial` と「記録した更新の和」は有限精度で異なり得るため、交換可能としない。
従来のreader tuple APIは残し、記録追加を新しい意味内容やconfidenceの証明にしない。

`functional_operator_contract()` は設定と構築済み演算子を照合する。
構築後にnorm種別・epsilon・logit加算設定を書き換えても、実行済み演算を別設定として
再表示できない。変更にはモデルの再構築が必要であり、runtime guardが不一致を拒否する。

## 実装と歴史的契約の識別

分割後の `source_sha256()` はengine単体ではなく、package直下の全 `*.py` の
名前とSHA-256を束ねたfingerprintを返す。scopeは
`package_top_level_python_modules_v1`。CLI本体と、使用するモデル/tokenizerの実装ファイルは
canary receiptへ別途記録する。これでも全transitive dependencyや将来のsub-packageの
完全な実装識別を自動的に保証するわけではない。

新しいconfig項目・version・source identityは明示的にV14のものになる。
旧checkpointのoptimizer再開同値性は主張せず、そのためにstrict guardを緩めない。
V13のdesign/visibility validatorとhash pinは変更しない。
対応テストだけがsealed `ed5ce398…` の歴史的ファイルを一時領域へ配置する。
V14のworking engineをV13の旧契約へ渡すと拒否されることもテストする。

## 最初の実モデルチェック

対象は `allenai/OLMo-2-0425-1B` のBASEモデル、revision
`a1847dff35000b4271fa70afc5db10fd29fedbdf`。16層、hidden width 2048。
Furnaceのローカルcacheで確認した2つのFP32 safetensors shardは計5,939,687,552 bytes。
実行時はこの固定snapshotをBF16としてロードする。downloadやremote codeは許可しない。

OLMo2もRMSNormだが、Q/K projectionの後と、attention/MLPの出力を残差へ加える前にnormがある。
Mistralのpre-branch normとは配置が異なり、今回のモデル境界分離に有用な対照となる。
LayerNorm対RMSNormだけの比較ではなく、サイズ・tokenizer・学習履歴も違うモデル間比較である。
今回測るのは各モデル内のnative/split一致であり、モデル間の性能優劣ではない。

実行は同じcommitとplanのもと、CUDA BF16のSDPA、続いてeagerを別processで逐次実行する。
3つの固定promptでcut 0/8/16の全logitを比較する。全parameterの勾配比較はcut 8のみで、
native backwardの勾配をCPUへ保存してからsplit backwardを行う。
optimizerは構築せず、parameterを更新しない。勾配計算があることと訓練を行うことを区別する。
最初の2 promptではnativeとcut 8の双方で4 tokenずつgreedy生成し、token ID列の完全一致を確認する。

BF16の固定許容差は、logitsが `atol=0.015625, rtol=0.0078125`、
gradientsが `atol=1e-5, rtol=0.02`。出力を見て調整しない。
padding込みの全logitを対象とし、勾配用CEはpadding targetを除いた固定next-input-tokenで計算する。
有限値・shape/dtype・全named parameterの勾配存在と一致を確認し、失敗したparameterを除外しない。
greedy一致や短い英文出力はpipeline確認であり、言語能力やworkspace有用性の結果ではない。

right padding、cache無効、最大96 input tokens、CPU演算2 threads、固定seed 1401。
pad tokenがなければ既存EOSを使い、語彙を追加しない。
各cellの前後でsnapshotの全ファイルと実装sourceのSHA-256を照合し、変更があれば失敗とする。
**8 GiBの上限はsnapshot全体のpayload量**であり、GPU使用量のhard capではない。
CUDA allocatorのpeak allocated/reservedは別の観測値として記録する。
SDPA設定は記録するが、実際にdispatchされたkernelを観測していなければ`UNKNOWN`を保つ。

NamedNormRecorderは先頭3つのinventoried normとnative `model.norm` を選び、
最大8 records・tensorあたり先頭4096要素に限定する。全選択moduleの呼び出しとcaptureを確認し、
観測を入れたnative出力が元の出力と完全一致することを要求する。
prefixの統計やhashを省略部分まで含む結果として報告しない。

planは実行前に固定する宣言であり、canary CLIがplan JSONを自動検証する実装ではない。
実行担当者はmodel revision/config、cell引数、source commit、plan hash、出力先を照合して記録する。
CLIが強制する制約と、この実行前照合を混同しない。
実際のreceiptが生成されるまで状態は`NOT_RUN`である。失敗・部分結果も残し、
両cellの結果を個別に報告する。SDPA/eagerの一方だけで全体を成功としない。

## 今回まだ主張しないこと

- 難しいtask corpusの適格化、内容固有のworkspace利用、意味の転送。
- 読み取り側と後続遷移側を独立に交差させ、復元・移植で媒介を示すR↔D bridge。
- 旧B/F1/O3の未完了比較の解消、旧optimizer再開、14Bへの拡張。
- norm除去の必要性、振幅=confidence、observerの記録が因果的有用性を証明するという解釈。
- 学習、checkpoint削除、cache変更。

cached Qwen2.5-0.5Bはより小さいがnorm配置はMistralに近い。
Gemma-2-2B-itはoffset付きscaleなどの次の対照候補である。
どちらもこの2-cell計画には含めず、追加実行を自動的に許可しない。
