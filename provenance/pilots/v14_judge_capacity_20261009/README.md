# V14：Mistral 16k完走と、残ったjudgeの盲点

2026-10-09。Mistral Large 4の上限を4,000から**16,384 tokens**へ広げ、
同じ140リクエストを別methodとして実行した。**140応答を保存、136件が厳密有効、
4件は引用不一致で除外。打ち切り・HTTP失敗・未送信は0件**だった。
5反復の実行とreceiptは閉じているが、全票が有効ではないため状態は
`NEW_METHOD_PARTIAL_OR_INVALID_RECEIPTS_NOT_GOLD`。品質合格を意味しない。

Claudeはmetadata GETの401後にユーザー判断で見送り。Claudeの生成・capacity probe・
study呼出しは0で、adapterは実装・mock検証のみ。鍵は成果物やzshrcへ保存していない。
[事前protocol](PROTOCOL.md)と、その後の[scope更新](SCOPE_UPDATE.md)を両方保持する。

## 読む入口

- [全回答・全判定理由・AB/BA・5反復の比較](analysis/PANEL_REVIEW.md)
- [機械可読な集計](analysis/SUMMARY.json)
- [引用不一致4件の原文参照・出力長診断](analysis/STRICT_DIAGNOSTICS.json)
- [実行記録](EXECUTION_NOTE.json)、[完全性の検証receipt](VALIDATION.json)
- [事前の容量確認](preflight/mistral_16384/QUALIFICATION.json)、[固定計画](../../../configs/v14/MISTRAL16384_JUDGE_PANEL_PLAN.json)
- [旧4k・OpenAI・Geminiの封印済み結果](../v14_judge_extension_20261009/README.md)

## 上限拡大で何が変わったか

事前固定の非study 3組×AB/BAは6/6件が厳密有効。同文controlは両順序tieで、
最大出力7,858 tokensが事前の75% headroom条件を通過した。
その後、commit `5e872eb43665b8e5eb7f48d54eb95c0f4e90e2a2` で計画を固定してから
studyを送った。32k・65kのcanaryは実行していない。

全140件について、旧MistralのAPI bodyから変えた項目が`max_tokens`だけであることと、
evaluator inputのhash一致を検証する。temperature 0.2、seeds 1001–1005、
reasoning_effort未指定、schema、rubric、回答、参照世界を維持した。
client timeoutは600から1,200秒へ変更。API返却IDは全件`mistral-large-4`だが、
previewのremote weightsが不変だったことまでは確認できない。

本評価のAPI報告出力は最小3,695／中央値7,154／最大14,988 tokens。
**139/140件が旧4,000上限を超えた**。全140件が`finish_reason: stop`で、
16k到達は0件。これはAPIのcompletion-token量であり、最終JSONの文字数ではない。
今回の入力集合で容量問題は解消したが、事前canaryより本評価の最大出力は長く、
16kで将来の全入力を保証するものではない。

| method | 計画 | 予約 | 保存応答 | 厳密有効 | 打ち切り | HTTP失敗 | 未送信 |
|---|---:|---:|---:|---:|---:|---:|---:|
| OpenAI（既存） | 140 | 140 | 140 | 140 | 0 | 0 | 0 |
| Gemini 3.8（既存） | 140 | 140 | 140 | 140 | 0 | 0 | 0 |
| Mistral 4k（旧） | 140 | 95 | 93 | 1 | 92 | 2 | 45 |
| Mistral 16k（新） | 140 | 140 | 140 | 136 | 0 | 0 | 0 |

新16kの残る4件は引用不一致。旧4kの有効1件は同文controlのAB側のみで、
変更組の有効票や有効なAB/BA組はない。旧失敗を新しい票で埋めず、分母も混ぜない。
既存OpenAI/GeminiのAPIは再送していない。新規学習・被評価モデルの回答生成・重み変更もない。

## 変更10組：三者の共通安定workspace選好は1組

W=workspace、B=base、T=tie、C=AB/BA不一致、I=無効・欠測。
各数字は5反復中の回数で、API呼出し数でも独立課題数でもない。
全5反復が有効・順序一致かつ同じ選好の場合だけ「安定」とする。

| case / regime | OpenAI | Gemini 3.8 | Mistral 16k |
|---|---|---|---|
| summary / greedy | T5 | T5 | T4 C1 |
| causal / greedy | W5 | T4 C1 | W3 C2 |
| causal / sample211 | W5 | W5 | W5 |
| clarification / greedy | B1 T2 C2 | T5 | T5 |
| clarification / sample212 | B3 C2 | T5 | T5 |
| relation-01-forward / sample211 | T5 | T5 | T1 I4 |
| relation-01-forward / sample212 | B1 C4 | B2 T1 C2 | T1 C4 |
| relation-03-forward / sample211 | C5 | T5 | B4 C1 |
| relation-04-forward / sample211 | T5 | T1 C4 | T5 |
| relation-04-reverse / sample211 | T3 C2 | T1 C4 | T5 |

変更10組の安定選好は、OpenAIがW2／T3／非安定5、GeminiがW1／T5／非安定4、
Mistral16kがW1／T4／非安定5。安定Bは三者とも0。
Mistralの非安定5組には引用不一致を含む1組があり、それをtieへ置き換えない。
別枠の同文control4組は三者とも全反復tie。

共通の安定Wは**causal / sample211だけ**。base80語→workspace54語となり、
60語制約内へ入る点は機械的にも確認できる。Mistralの全10 order-callもこの差に言及する。
別チーム・固定loggingの検証案を好む説明もある一方、同時期のno-checklist対照群や
無作為化は回答に明示されていない。Mistral r3 ABなどはその不足を認めて語数遵守を
決め手とするが、他の説明には対照比較を読み足すものもある。
票の一致を、説明の一致・因果識別の成功・潜在知能の抽出へ格上げしない。

## 容量とは別に残った三つの盲点

1. **引用を作り替える。** `relation-01-forward / sample211` のr1–r4、BAの4件。
   B側の原文は `such as a particular category or competition` だが、
   引用には原文にない `in` が入った。いずれも正常終了したJSONだが厳密検証で除外。
   [診断JSON](analysis/STRICT_DIAGNOSTICS.json)に各raw hashと不一致引用を保存した。
   近接する二文の混同が疑われるが、内部機序の証明ではない。修復・再判定はしていない。
2. **語数を誤認する。** `relation-03-forward / sample211` は29→32語で、
   workspaceだけが30語制約を破る。MistralはB4 C1だが、r0 BAでは両方30語内と
   誤認してtieにした。OpenAI/Geminiにも語数誤認の実例があり、Mistralだけなら
   計器が正しくなるわけではない。機械的語数注記は既存の票を上書きしない。
3. **勝敗が安定しても評点は安定とは限らない。** `clarification / greedy` のr0では、
   AB/BAともtieだが、両回答のcalibration評点がABの0からBAの4へ変わる。
   ABは制約無視を過信と捉え、BAは締切を捏造しない点を評価していた。
   これは具体例であり、全課題についての順序効果の推定ではない。

確認質問の2組でMistral/GeminiがT5となる理由は、可視範囲で既に質問数超過や
質問から指示文への逸脱を両者が共有するため。切断された続きを都合よく補わない。
順位課題では、query-only baseとfact-bearing workspaceの情報量を同一視しない。
Noが同じ、文が自然、judgeがtieというだけではmemoryへのgrounding成功にはならない。

## 学習機へ戻す順番：提案のみ、未学習

[既存の設計追補](../../../docs/v14/JUDGE_EXTENSION_LEARNER_UPDATE.md)のG0/G1優先は維持する。
今回の追加judgeは、選好ラベルをそのまま学習目標にする根拠を増やしてはいない。

- 評価計器の次protocolでは、語数等の再現可能な検査をLLMから分離し、両回答へ対称に
  提示する案を検証する。引用は自由な再生成ではなく、検証可能なspan ID等を候補にする。
  いずれも全providerに対する別methodとして事前固定し、現在の票の修正には使わない。
- G0でnative readoutとzero経路の実装同一性を維持し、G1を新規holdoutの無学習対照で通す。
  intact／twin／別事実・同schema／別事実・別schema／norm-matched randomを区別する。
  旧unrelatedの同schema性を「意味なし」と一括しない。
- その結果から、事実利用・課題構造の転用・一般的摂動を切り分け、損失項ごとの勾配を
  調べてから一変数ずつ変更する。task-aware gateやpreservationの変更は候補であり、
  現在の失敗原因や解決策として確定していない。選択済み10組へのDPO等は行わない。

変更10組は7 prompt・6 task/world clusterであり、反復や3つのjudgeを独立課題として
水増ししない。比較したのはprovider/model/settingsの組で、familyだけの効果は未分離。
`winner: none`、非劣性未確立、人間評価PENDING、内容因果性未確立を維持する。

## 実行・費用・検証

本評価はUTC 2026-10-09 01:04:54.585765から02:04:21.118455まで。
5プロセスともexit 0。自動再送、JSON/引用修復、結果による早期停止はない。

本評価の報告usageは入力252,860／出力1,043,885／合計1,296,745 tokens。
割引を考慮しない従来の$1.36/$4.18 per millionで **$4.70732890**。
容量確認6件は別枠 **$0.15036754**、今回の両者合計の推定は **$4.85769644**。
実請求額・割引はUNKNOWN。140件の事前保守上限は$10.89158560であり、請求額ではない。

関連ローカル検証は **506 passed / 8 skipped**、対象Ruff PASS。
8 skipはユーザー判断で見送ったClaude studyの集計variant。
旧547 artifactsと、その参照先の316／102 artifactsは変更せず再検証PASS。
新規INDEX/VALIDATIONは完全性・再構成の検査で、judgeの正しさや品質認定ではない。

以下はネットワーク呼出しなしの再検証であり、評価APIを再送しない。

```bash
python3 scripts/seal_v14_budget_panel.py --plan configs/v14/MISTRAL16384_JUDGE_PANEL_PLAN.json
PYTHONPATH=src python3 -m pytest -q tests/*answer_bank*.py tests/*v14*panel*.py tests/*v14*extension*.py tests/test_v14_mistral_budget.py tests/test_v14_budget_reporting.py
```

旧bundle/sourceは不変。新bundleのINDEX/VALIDATIONを含む追補として公開し、
PRはDraftを維持する。CI成功、mainへの統合、mergeを行ったという主張はしない。
