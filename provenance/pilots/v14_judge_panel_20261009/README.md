# V14：変わった回答を反復 blind judge にかけ直す

2026-10-09。**OpenAI 140/140 応答・140/140 厳密有効。Mistral 0/140、未実行。**
全体は `VERIFIED_PARTIAL_RECEIPTS_NOT_GOLD`。他系列との比較はまだ成立していない。
新規生成・学習・重み変更／削除は行っていない。科学的判定は引き続き `winner: none`。

## 何を追加したか

封印済み回答バンクの 96 primary pairs から、文章が変わった **全 10 組**を選択した。
旧 judge の好みは選択に使っていない。全 10 組が legacy semantic と base の比較であり、
centered reader の成功例ではない。7 prompt、6 world/task clusters に属する。
同文校正には、JSON・code・関係課題 2 件の実際に同一な 4 組を別枠で加えた。

`gpt-5.4-2026-03-05` に、各 14 組 × AB/BA 両順序 × 5 反復を依頼した。
5 反復は同一 judge の別呼び出しであり、5 人の独立した judge ではない。
モデル／訓練条件の名前と過去の判定は提示していない。
前回と同じ厳密な引用検証を維持し、引用符を余分に付けない指示だけを事前に明確化した。
今回は事後修復なし。前回の一次結果・引用符修復補助結果とは混ぜない。

## 観測された傾向

「安定」は **5 反復すべてで AB/BA が有効かつ一致し、同じ選好**になった場合だけを指す。

| 変更 10 組の結果 | 組数 | 内容 |
|---|---:|---|
| workspace 選好が安定 | 2 | 同じ因果課題の greedy と sample211 |
| tie が安定 | 3 | 要約、relation-01/sample211、relation-04-forward/sample211 |
| いずれかの反復で順序不一致 | 5 | 日本語確認質問 2 組、関係課題 3 組 |
| base 選好が安定 | 0 | 部分的な base 選好は上の不一致群に残す |

同文校正 4 組はすべて 5/5 反復で tie、計 40/40 応答が tie だった。
一方、relation-03-forward/sample211 は **全 5 反復が順序不一致**だった。
多数決で一つの勝敗へ丸めると、この測定上の弱点が隠れる。

全 14 組の早見表、回答、各反復・各順序の根拠、引用全文は
[PANEL_REVIEW.md](analysis/PANEL_REVIEW.md)、機械可読集計は
[SUMMARY.json](analysis/SUMMARY.json)。旧バンク全体と比較した品質改善率ではない。

## 良く見えた変化と、まだ言えないこと

因果課題の greedy では、checklist を一時中断して観察する案から、別の controlled group
へ導入する案に変わった。sample211 では、前後比較から別チームで logging を揃える案へ
変わり、空白区切り語数も base 80 → workspace 54 で、60 語制約に収まった。
この 2 組はそれぞれ **10/10 応答で workspace 選好**だった。

ただし独立した 2 課題の改善ではない。greedy は base 79／workspace 80 語で両方違反し、
workspace 案にも無作為化や未介入群の明示がない。`controlled` という語を judge が
好んだ可能性を排除できない。「比較を意識した提案へ変化」は読めるが、
「妥当な因果実験設計を獲得した」「memory の意味を使えた」とは言えない。

日本語確認質問は、双方とも指定の 2 問を超えて列挙し、128-token cap で切れている。
関係課題では、初頭の No は変更 5 組すべてで同じで、説明の言い換えや作話の変化が中心。
正答ラベルが偶然合った場合も、根拠が正しくなったこととは分ける。

## judge 自身の失敗も保存する

以下は元回答・rubric と照合した **非 blind のエージェント読解メモ**であり、
独立した追加 judge 票や人間評価ではない。

- relation-01/sample212 は base 33／workspace 30 語なのに、一部の judge は
  両者が 30 語を超えると説明した。
  [r0/BA の判定](cells/openai/r0/requests/openai-r0-7f7a35312c1785cce85a-BA.json)。
- relation-03/sample211 は base 29／workspace 32 語なのに、両方が超過するという説明がある。
  [r0/BA の判定](cells/openai/r0/requests/openai-r0-1915711d71c2e39d8256-BA.json)。
- 要約は双方とも `during a two-hour tracking blackout` と書き、原資料が明示していない
  遅配と tracking outage の同時性を含めている。tie や高い評価でも事実保持の保証ではない。
  [r0/BA の判定](cells/openai/r0/requests/openai-r0-8fccf16891940b824bd3-BA.json)。

この発見を受け、英語の語数上限がある **全選択組**に `len(answer.split())` による
事後的・記述的な機械チェックを併記した。日本語の語数や文の意味の検証には使わない。
この追加チェックで judge の票を修復・上書きしたり、選択組を変更したりしていない。
厳密有効 140/140 は JSON・引用等の契約通過であり、推論内容の正しさではない。

## 次の学習機更新へどう戻すか

[詳細設計案](../../../docs/v14/JUDGE_PANEL_LEARNER_PROPOSAL.md) は
`PROPOSED / NOT_TRAINED`。次の順序を提案する。

1. 保持中の **同じ legacy 重み**で、intact / zero / unrelated / twin / norm-matched random
   を無学習で比較する。全変更 10 組だけでなく既存 48 組全体と、別の新規 holdout を分ける。
2. full-vocabulary native readout のモデル依存演算を binding に閉じ込め、zero/native parity
   を先に通す。固定 prefix と自由生成の差を混同しない。
3. train-only の逆質問で損失項ごとの勾配の相殺を測る。その結果に応じ、query 表現、
   不要介入での base-preservation、内容対照損失、selective gate を一変数ずつ比較する。

現在のバンクで zero/unrelated/twin を揃えたのは centered 側であり、legacy の良い変化の
内容因果性は未識別。この回答や judge ラベルをそのまま DPO 等の正解データへ流さない。
base 保持は既知の誤りを無差別に固定する目的でもない。不要介入を抑える領域と、
正しい内容に基づく有用な変更を学ぶ領域を別に定義する。

## Mistral の状態

公式情報で Large 4 の 2026-10-06 Public Preview を確認し、計画は明示 ID
`mistral-large-4` を指定した。`mistral-large-latest` が指す版は確認できていない。
同系統 judge の一致も独立した真値ではなく、provider・sampling の差も残る。

ローカル環境で Mistral 用キーが見つからず、設定場所を問い合わせた状態。
**未実行 140 件を tie や成功に置き換えていない。** 後日実行する際も、この partial bundle
を上書きせず追加証拠を別 bundle として保存する。
[公式モデル情報](https://docs.mistral.ai/models/mistral-large)、
[凍結プロトコル](PROTOCOL.md)、[実行注記](EXECUTION_NOTE.json)。

## 実行・再現・費用

- 実行前固定 commit: `29af1074af380660d728e3221e400558e3e0cc79`。
- OpenAI 実行: 2026-10-08 19:05:25.887616–19:14:33.945419 UTC、5 セル並行、各セル逐次。
- reported input 198,820 / output 156,183 tokens。
- 割引なし単価での usage estimate **$2.839795**。実請求額は `UNKNOWN`。
- raw request/response、model ID、timestamp、usage、hash を [cells](cells/openai/) に保存。
  API キー・重みは含めない。
- 新 panel 79 件と旧 answer-bank 168 件、計 **247 の関連ローカルテストが PASS**。
  対象の新規 source/test に対する Ruff も PASS。全リポジトリの test suite や CI の主張ではない。
- [INDEX.json](INDEX.json) の全ファイル閉包と hash、selection、raw 応答からの判定／集計、
  readable report を再構築する。[VALIDATION.json](VALIDATION.json) は artifact 整合性の検証。
  quality proof、他系列比較の完了、CI、merge を意味しない。
- 人間評価は `PENDING`。元の [blind sheet](../v14_answer_bank_20261009/reader/HUMAN_REVIEW.md)
  と blank human score sheet は変更していない。

```sh
python3 scripts/prepare_v14_judge_panel.py --check
python3 scripts/seal_v14_judge_panel.py --verify
python3 provenance/pilots/v14_answer_bank_20261009/verify.py
PYTHONPATH=src python3 -m pytest -q tests/test_v14_judge_panel.py \
  tests/test_v14_panel_selection.py tests/test_v14_panel_summary.py tests/test_v14_panel_seal.py
```
