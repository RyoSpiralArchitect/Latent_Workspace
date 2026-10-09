# V14：追加judgeと「何に無関係か」の再分離

2026-10-09。状態 **PROPOSED / NOT_TRAINED**。
旧[設計案](JUDGE_PANEL_LEARNER_PROPOSAL.md)は封印済みのまま維持し、本書を追補する。
新規学習・生成・重み変更は行っていない。追加judgeの実行結果は
[追加パネル](../../provenance/pilots/v14_judge_extension_20261009/README.md)で区別する。

## 追加実測：一致したのは一つの生成条件。理由まで同じではない

Gemini 3.8 Flashは140/140件が厳密有効。旧OpenAI140件との対比では、変更10組の
5反復安定選好はOpenAIがworkspace2／tie3／非安定5、Geminiがworkspace1／tie5／非安定4。
両者が安定してworkspaceを選んだ共通組は **causal / sample211だけ**だった。
同じ課題のgreedyはOpenAIがworkspace5回、Geminiはtie4回とAB/BA不一致1回。
ここでの5回は独立した5課題ではない。

sample211の80→54語という制約内への短縮は機械的にも確認できる。
ただしGeminiの理由は主に語数制約、OpenAIの理由は主に比較実験案への評価であり、
票の一致は因果的な説明の一致ではない。両judgeとも、実際には明示されていない
no-checklist側の対照を回答へ読み足す場合がある。さらに両者の語数値は誤ることがある。
OpenAI r1 ABとr3 BAは、54語のworkspaceも60語超と述べていた。
Gemini r0 ABは80/54語の回答を66/48語と数えている。
現在の票は修復せず、[全説明と機械チェック](../../provenance/pilots/v14_judge_extension_20261009/analysis/PANEL_REVIEW.md)
を併記する。

関係課題でも、29→32語の制約退行をGeminiが両方30語内と数えてtieにする例がある。
別の組では、AB/BA順序によって語数の認識まで変わっていた。
架空の理由が「自然」と好まれることも、memoryへのgrounding成功とは区別する。
次のjudge方法では、語数など再現可能な制約検査をLLMの説明から分離し、
必要ならその検査結果を両回答について対称に提示する別protocolを設計する。
この選択済みバンクを使った事後的な票の訂正や、judgeラベルへの直接学習は行わない。

同一文control4組は両者とも全反復tie。ただしこれは同等な入力の扱いの校正であり、
共通して誤った回答を正しく評価できたことや、評価理由の正確さまで証明しない。
judgeが「両モデルに世界情報がなかった」と推測しても、出力だけから入力経路は
復元できない。実験上はquery-only baseとfact-bearing workspaceを区別し、
judgeの推測を内部状態の観測へ格上げしない。

Mistralは95件予約／93応答のうち92件が4,000-token上限で打ち切られ、有効1件は
同一文controlのみ。80応答はfinal textなし、12応答は最終JSONが途中だった。
HTTP 500が2件、未送信45件を残す。変更組の有効票は0で、3-family比較は未成立。
次回は長さを含めて代表的な非study入力で上限拡大を確認し、別の事前固定methodとして
実行する案を優先する。reasoningを無効化するなら、同じjudge条件とは呼ばない。

## 結論：G0/G1を先に通す。ただし「unrelated」を一種類の負例にしない

旧設計案の優先順は維持する。まず通常base・zero・保持checkpoint・native full-headの
実装同一性を固定し、無学習で内容対照と新しいholdoutを測る。
その前に、対照の解釈を一段細かくする必要がある。

既存の[causal課題](../../data/v14_answer_bank/cases.json)の
`unrelated_memory_text`は、checklist/errors/loggingをlunch/soup/bowlsへ置き換えても、
**同じ週の別変更・対照群なし**という因果課題の構造を共有している。
これは対象事実には無関係だが、推論の型まで無関係とは言えない。
ただしbowlsの変更が測定手順の変更と同じ意味になるとは限らず、因果グラフまで
完全に同一だという主張ではない。
関係課題の別entityランキングも同様に、推移的順位という課題構造を共有する。

したがって旧unrelatedでも有用な変化が出た場合、少なくとも以下が残る。

- memory内容と無関係な、一般的なreadout摂動。
- 対象事実は使っていないが、類似課題の構造を利用した抽象的な転用。
- writer/reader表現や振幅、長さなどの差との交絡。

これらを票数だけで決めない。旧データやラベルを変更せず、旧unrelatedは
「事実非関連・同schema」と事後注記する。次の新規計画では意味を事前固定する。

## 次の無学習パネルに加える対照

| 条件 | 何を主に区別するか | 残る交絡／境界 |
|---|---|---|
| direct base / 書込み後zero | 経路の実装同一性、介入なしの基準 | 有用性や内容利用を単独で証明しない |
| intact | 対象事実と課題構造を含む内容 | 両者を同時に変えるので寄与は未分離 |
| 旧unrelated：別事実・同schema | 題材を越えた構造利用の候補 | 表現や摂動の一般効果とも区別が必要 |
| 新規：別事実・別schema | 同schema効果との対照 | 長さ・文体・slot数・normを観測し、完全一致とは言わない |
| 事前seedのnorm-matched random | テキスト意味を持たないcarrierとの対照 | memory norm一致はresidual/logit振幅一致ではない |
| twin / unaffected | authoritativeな最小事実変更への方向性と保存 | visible user factsをmemoryが上書きすれば成功ではない |

これは直ちに完全な2×2要因実験になるわけではない。「事実関連・別schema」の
自然で曖昧さのない操作を定義できるかは未解決である。
最初は解釈可能な対照集合として扱い、整っていない直交性を主張しない。
現在の48 case-regimeは開発集合。新holdoutは独立world/taskを生成前に固定し、
結果が良かった／変わったことを選定条件にしない。

## judgeが好む文章と、解けた課題を分ける

追加評価前に確定していたOpenAIの安定workspace選好2組は、同じ因果課題の
greedyとsample211であり、独立した2課題ではない。

- greedyは79→80語で両方とも60語制約を破る。
- sample211は80→54語で制約内になる。
- 変更後には別チームと固定loggingを用いた検証案がある。一方で、checklist群と
  no-checklist群の同時比較は明示されず、無作為化も書かれていない。
  judgeが「対照比較」を読み足しても、それを回答に実在した設計と数えない。

保持したい仮説は「測定条件を固定し、検証案を具体化する変化を引き出せるか」。
未達の比較群・因果識別・語数は別々に残す。judgeに好まれた表現へ学習することが
そのまま潜在能力の抽出にはならない。

関係課題の変更5組は先頭のNoが変わらず、intact workspaceの4つのforward組では
memory worldの正答yesと不一致。baseはqueryしか見ないため、これを同じ情報量での
base対比のaccuracy退行と解釈しない。
reverseでNoが正しくても、説明が架空の設定を付け足していればgrounding成功ではない。
確認質問では、切断前から質問数超過や指示文への変化が見られる。token上限だけを直せば
解決するとは言えない。これらは事後読解であり、既存のjudge票は書き換えない。

## 学習機へ還元する際の変更順

1. **native readout bindingとpreservationの計器を維持する。** モデル固有のnorm・
   dtype・headの差を明示し、同一prefixでfull-vocabulary差と内容方向性を観測する。
2. **負例の意味を監査する。** 既存の
   [objective](../../scripts/run_v14_precision_bridge.py)は二候補logitの
   `unrelated_gap_square`をbaseへ寄せる。この二択課題の実装を、自由文でも
   「事実非関連なら全変化を罰する」という規則へそのまま拡張しない。
   同schemaの有用な転用まで抑える可能性は新仮説であり、現在の失敗原因と断定しない。
3. **損失項別の勾配・質問方向・内容方向をtrain-onlyで分解する。** 現行損失の相殺や
   candidate-only supervisionを調べる。gain増大やreader大型化を先に正当化しない。
4. **対照結果に応じて一変数ずつ変更する。** 事実利用ならquery–memory interaction、
   構造転用ならtask-aware relevance/gate、一般摂動ならpreservationと介入の選択性を
   候補にする。正解ラベルやjudgeだけで分岐を確定せず、matched controlsで裏づける。

「baseを割らない」と「有用な変化を引き出す」は両方の目標として維持する。
この小さな選択済みバンクに合わせて非劣性marginを選ばない。現在は
`winner: none`、非劣性未確立、人間評価未実施のままである。
