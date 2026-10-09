# V14追加judge：Gemini完了、Mistralは計器不成立

2026-10-09 JST。**Gemini 3.8 Flashは140/140件が厳密有効**。
旧OpenAI結果と比べ、両者共通の5反復安定workspace選好は
**general-05-causal / sample211の1組**だった。
Mistralは出力予算・通信の失敗で比較不能。3-family比較完了でも、モデル品質改善の
証明でもない。状態は VERIFIED_PARTIAL_RECEIPTS_NOT_GOLD、winner: none。

## 分母と欠測

| Provider / method | 計画 | 予約・送信 | 保存応答 | 厳密有効 | 上限で未完成 | HTTP失敗 | 未送信 |
|---|---:|---:|---:|---:|---:|---:|---:|
| OpenAI既存snapshot、low（再利用） | 140 | 140 | 140 | 140 | 0 | 0 | 0 |
| Mistral Large 4、reasoning指定なし、4,000上限 | 140 | 95 | 93 | 1 | 92 | 2 | 45 |
| Gemini 3.8 Flash、LOW、4,000上限 | 140 | 140 | 140 | 140 | 0 | 0 | 0 |

全420予定のうちOpenAI140件は再利用で、新規送信は235件。
Mistralの有効1件は同文controlのAB側だけ。変更組の有効票も、成立したAB/BA組も0。
失敗をtieや負けへ変換しない。全ローカル実行は終了しており、自動再送は行っていない。
4件の非study接続canaryはこの表に含めない。

参照：[実行記録](EXECUTION_NOTE.json)、[機械可読集計](analysis/SUMMARY.json)、
[Mistral予算診断](diagnostics/MISTRAL_OUTPUT_BUDGET.json)。

## 変更10組の比較

安定は「5反復すべてでAB/BAが有効・一致し、その選好も同一」の厳しい定義。
反復を独立課題数に数えない。10組は7 prompt / 6 world-task clusterに集中する。
選択済み差分バンクなので、全体品質や非劣性の推定には使わない。

| 変更組 | OpenAI | Gemini 3.8 |
|---|---|---|
| summary / greedy | 安定tie | 安定tie |
| causal / greedy | 安定workspace | tie4、不一致1 |
| causal / sample211 | 安定workspace | 安定workspace |
| clarification / greedy | base1、tie2、不一致2 | 安定tie |
| clarification / sample212 | base3、不一致2 | 安定tie |
| relation01 forward / sample211 | 安定tie | 安定tie |
| relation01 forward / sample212 | base1、不一致4 | base2、tie1、不一致2 |
| relation03 forward / sample211 | 不一致5 | 安定tie |
| relation04 forward / sample211 | 安定tie | tie1、不一致4 |
| relation04 reverse / sample211 | tie3、不一致2 | tie1、不一致4 |

安定workspace / tie / 非安定はOpenAIが2 / 3 / 5、Geminiが1 / 5 / 4。
同文校正4組は両者とも全5反復tie。ただし同等入力の扱いの校正であり、
共通して誤った回答を正しく評価できることまでは証明しない。

[全回答・全反復の説明・機械的制約チェック](analysis/PANEL_REVIEW.md)は、
prompt、base/workspaceの原文、順序別判定、raw参照まで折り畳みで閲覧できる。

## 実際に残った手触りとjudgeの限界

- causal / sample211は80→54語で60語制約を満たす。慎重な結論と追試案を
  短く整理した変化は、2つのjudge設定で繰り返し好まれた。
  ただし回答はno-checklist群との同時比較を明示していない。
- 同じ課題のgreedyは79→80語で両方が制約違反。OpenAIは追試案を評価し、
  Geminiは主に同等と判断した。票の一致・不一致と、理由の妥当性は別である。
- 両judgeとも語数を誤認し、「対照群」を回答へ読み足すことがある。
  例としてGemini r0のsample211 ABは実際80/54語を66/48語と記述した。
  relation03 forwardでは29→32語の制約退行をGeminiが両方30語内と扱った。
  現在の票は修復せず、事後の機械チェックを別に併記する。
- 関係課題の説明の自然さ・簡潔さへの選好は、memoryへのgrounding成功とは違う。
  架空の設定同士でも選好は生じうる。モデルの内部状態や受け取った情報についての
  judgeの推測を、実験で観測した事実に置き換えない。

[learner追補](../../../docs/v14/JUDGE_EXTENSION_LEARNER_UPDATE.md)では、
G0/G1（base/zero同一性、内容対照、新holdout）を先に通す方針を維持した。
新しい重要点は、既存unrelatedが「別事実でも同じ課題構造」を共有すること。
次は事実関連性と課題構造関連性を区別し、抽象的転用を一般的な摂動と混同しない。
新規学習・回答生成・重み変更は行っていない。

## Mistralと接続preflight

Mistralの92未完成応答は全てfinish_reason=length、completion_tokens=4,000。
80応答はfinal textなし、12応答は最終JSONが途中。thinkingとfinalの正確なtoken内訳は
未報告なので、思考token比率を推測しない。HTTP 500が2件あったr0/r4は停止し、
曖昧な要求を再送しなかった。これはjudge側の実行条件の不成立であり、
workspace品質やMistralの判断能力への否定票ではない。

次のMistral評価は、代表的な長さの非study入力で上限拡大を確認したうえで、
別methodとして固定する案。reasoning無効化も条件変更として分離する。
今回のrunを上書き・部分修復・好ましい例だけ再評価しない。

Gemini 3.7要求→3.8返却の不一致は[元qualification](preflight/QUALIFICATION.json)と
[metadata記録](preflight/MODEL_METADATA.json)に保存。
ユーザー承認後の[3.8事前変更計画](GEMINI38_AMENDMENT.md)では3.8を明示し、
[新canary](preflight/gemini_3_8/REQUEST.json)がID・schema・引用・tie・usageを通過した。
3.1 Proと3.7要求のcanaryを本評価へ混ぜていない。3.7不一致の原因はUNKNOWN。

## 費用と検証

- Gemini140応答：入力129,430、出力87,467 tokens、公開料金での推計 $0.42507375。
- Mistral93応答：入力167,726、出力371,768 tokens、保守的料金で $1.78209760。
- 再利用OpenAI140応答：既記録 $2.83979500。全study報告使用量の合計推計は $5.04696635。
- 非study canary費用は上記から除外。Mistral HTTP失敗2件の使用量・費用はUNKNOWN。
  キャッシュ・account/free-tier割引を推測せず、実請求額もUNKNOWN。
- 関連ローカル469 tests、対象Ruff、旧answer-bank102／旧panel316 artifactsの検証PASS。
- 新規結果はrawから集計・reader・4 canary・Mistral診断を再構築して検証する。
  [INDEX](INDEX.json)／[VALIDATION](VALIDATION.json)は完全性の証拠であり、
  judgeの正しさ・人間同意・CI成功・学習改善の証拠ではない。

再現（ネットワーク・API・GPU・重み読込みなし）：

    PYTHONPATH=src python3 -m pytest -q tests/*answer_bank*.py tests/*v14*panel*.py tests/*v14*extension*.py tests/test_v14_mistral_budget.py
    python3 scripts/seal_v14_judge_extension.py --verify
    python3 scripts/seal_v14_judge_panel.py --verify
    python3 provenance/pilots/v14_answer_bank_20261009/verify.py

実行commitはMistralが8ce1cb1、Geminiがba64299。
旧bundleは不変。歴史的な[進捗snapshot](progress/STATUS_20261009T0506JST.json)は
当時の記録として残し、現在の完了状態と混同しない。
人間評価PENDING、非劣性NOT_ESTABLISHED、semantic promotionなし。
