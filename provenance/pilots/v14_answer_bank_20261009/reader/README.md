# V14 回答バンク：探索用資料

336回答・96比較対を、選別せず残した資料です。人間評価は未実施です。

先に [HUMAN_REVIEW.md](HUMAN_REVIEW.md) を読み、[human_scores.csv](human_scores.csv) に記入できます。 条件対応は [HUMAN_KEY.json](HUMAN_KEY.json) に分離しています。

全条件の回答は [ANSWER_BANK.md](ANSWER_BANK.md)、LLMの観察は [JUDGE_REVIEW.md](JUDGE_REVIEW.md) にあります。

## 計数（品質評価ではありません）

<pre>{
  &quot;comparison_counts&quot;: {
    &quot;general/centered_semantic&quot;: {
      &quot;identical_text_pairs&quot;: 24,
      &quot;identical_token_pairs&quot;: 24,
      &quot;pairs&quot;: 24
    },
    &quot;general/legacy_semantic&quot;: {
      &quot;identical_text_pairs&quot;: 19,
      &quot;identical_token_pairs&quot;: 19,
      &quot;pairs&quot;: 24
    },
    &quot;relation/centered_semantic&quot;: {
      &quot;identical_text_pairs&quot;: 24,
      &quot;identical_token_pairs&quot;: 24,
      &quot;pairs&quot;: 24
    },
    &quot;relation/legacy_semantic&quot;: {
      &quot;identical_text_pairs&quot;: 19,
      &quot;identical_token_pairs&quot;: 19,
      &quot;pairs&quot;: 24
    }
  },
  &quot;denominators&quot;: {
    &quot;answers&quot;: 336,
    &quot;cases&quot;: 16,
    &quot;conditions&quot;: 7,
    &quot;general_tasks&quot;: 8,
    &quot;human_pairs&quot;: 96,
    &quot;regimes&quot;: 3,
    &quot;relation_worlds&quot;: 4
  },
  &quot;finish_counts&quot;: {
    &quot;eos&quot;: 289,
    &quot;length&quot;: 47
  }
}</pre>

## 解釈の境界

- 定性的な探索用バンクです。潜在的知能の向上、一般的優越、非劣性は未確立です。
- 16問は独立16世界ではありません。関係8問は4世界の順逆対で、一般課題は8問です。
- 同じ問題の3生成条件は独立した問題標本ではありません。
- 一般課題だけが同じ必要情報を見せる比較です。関係課題の情報アクセス差とは分けて読みます。
- 同一seed・共通乱数は生成を対応づけますが、文章差を意味的改善に変換する保証ではありません。
- length終了は未完了の可能性を残します。eos終了も課題達成や正しさを保証しません。
- LLM評価は誤り得る観察で、人間の評価ラベルではありません。人間評価は未記入です。
