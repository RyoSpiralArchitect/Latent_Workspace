# V14 judge追加：実行中・モデルID hold

**PROVISIONAL / NOT_SEALED**。2026-10-09 05:06 JST時点の経過記録。
最終結果でも、3-family比較の完了報告でもない。

## 状態

- OpenAI：旧[封印panel](../v14_judge_panel_20261009/README.md)の140件を参照。
  追加実行していない。旧bundleは変更していない。
- Mistral Large 4：5反復×28件を開始。r0/r4はHTTP 500を各1回受けて計画どおり停止、
  自動再送なし。r1/r2/r3は上記時点で稼働中。4,000出力token上限に達する
  未完成応答が多く、判定票として扱えない。詳細は
  [時刻付き進捗スナップショット](progress/STATUS_20261009T0506JST.json)。
- Gemini：ユーザー指定は`gemini-3.7-flash`。接続canaryの返却IDは
  `gemini-3.8-flash`であり、**本評価0/140、送信前gateでBLOCKED**。
  3.8へ自動で置き換えない。モデル変更の判断待ち。

この拡張の分母は再利用OpenAI 140＋Mistral 140＋Gemini 140＝420。
未完成・API障害・未送信は別々に残す。進行中のMistral raw study receiptsは
ローカルの`cells/mistral/r0`〜`r4`に保存しており、まだ公開・封印していない。
本bundleのINDEX/VALIDATIONと最終集計は、実行終了後に作る。

## 接続確認と返却形式

[qualification](preflight/QUALIFICATION.json)は、3件の非study canaryを区別する。
最初のGemini 3.1 Pro canaryはモデル変更前の接続確認に限り、本評価へ混ぜない。
3.7 canaryはAPI本文の形式確認には通ったが、返却モデル同一性は不合格。
[モデル情報](preflight/MODEL_METADATA.json)では3.7が存在する一方、生成応答は3.8を
名乗る。原因はUNKNOWN。3.7の廃止や3.7と3.8の同一性を推測しない。

Mistral canaryはAPI応答成功後、旧string-only parserで失敗した。
新adapterでthinking/final-textの返却形式を解き、元の厳密schema・引用検証で
同じ保存済み応答を再検証した。APIの再送、引用文字列や判定の修復は行っていない。

## 次の設計に戻すこと

[learner追補](../../../docs/v14/JUDGE_EXTENSION_LEARNER_UPDATE.md)の主眼は、
既存`unrelated`を「事実非関連」と「課題構造非関連」に分けること。
同じ因果構造を残した別題材memoryから有用な変化が出ても、直ちに内容非依存の
摂動と断定できない。既存データは変えず、新しい対照とholdoutで切り分ける提案である。
新規学習・生成・重み変更は行っていない。

## 検証と続行時の注意

- 関連ローカルテスト365件PASS。Ruff PASS。
- 旧answer-bank 102 artifacts、旧panel 316 artifactsの検証PASS。
- Geminiの実計画が、出力予約・キー参照・送信前に拒否されることも確認。
- Mistral実行commitは`8ce1cb1d05977c46cfe6a613caa536e457be000e`。
  後続commitのGemini guard追加は、Mistralの要求本文・source bindingを変えていない。

実行中セルを重複起動しない。終了／HTTP failureの記録を確認し、曖昧な要求を再送しない。
終了後にEXECUTION_NOTE、rawからのSUMMARY/PANEL_REVIEW、INDEX/VALIDATIONを作成する。
現在の低い有効率をfamily評価の負けやモデル品質の悪化と解釈しない。
出力予算を変える場合は新しい方法として事前固定し、このrunを上書きしない。
`winner: none`、非劣性未確立、人間評価未実施。CI成功や科学的成功の主張はない。
