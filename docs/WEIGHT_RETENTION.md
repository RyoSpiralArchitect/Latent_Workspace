# 条件別の重み保存方針

2026-09-04。ユーザーの「各条件、の方だ！」という訂正を反映する。
「最新と1個前」は **各実験条件の最新2 checkpoint** であり、V12/V11という2世代ではない。
今回、重みは1件も削除していない。

## 保存単位

- checkpointはファイル1個ではなく、workspace・base shards・trainer state・manifestを含む保存bundle。
- 条件、seed、model/revision、学習率・objective・データ・実装・独立trialを混ぜない。
  保存系列の同一性が明示されていない別output directoryは、安全側で別系列とする。
- 同一系列内ではmanifestの`global_step`で順序づけ、最新2つの異なるstepを残す。
  ファイルの更新日時は学習順序の根拠にしない。
- 同じstepの`final`と`checkpoint-N`は同一payloadとは限らないので、今回は両方残す。
  resume分岐はrun_idを引き継ぐ場合があり、run_idやsignatureだけで別runを統合しない。
- 不完全・判定不能・使用中の保存、明示的に選択されたbestや診断参照中の重みは保護する。
  基盤モデルcacheと他プロジェクトは対象外。

これは保守的な保持判定であり、異なる試行の整理・重複排除を実行したという意味ではない。

## 今回確認した範囲

| 範囲 | 重み/stateファイル | bundle役割数 | 明示的な実行系列 | 最新2stepより古い対象 |
| --- | ---: | ---: | ---: | ---: |
| 手元V9 experiments | 90 | 30 | 30 | 0 |
| 手元V9 resume_gates | 9 | 3 | 2 | 0 |
| 炉V10 runs/v10 | 140 | 70 | 42 | 0 |
| 炉V11/V12の5 run root、manifest付き保存 | 228 | 38 | 37 | 0 |

手元V9と炉V10は239ファイル・42,651,277,759論理bytesをhash化し、
config/metrics等2,532ファイルを別保存した。重み内容のbackupは作成していない。
V11/V12はmanifest hashとファイル数・容量を確認しただけで、重み内容のhash化はしていない。
manifestのない保存や他のrun rootまで含む全ストレージ走査ではない。

- V9 experimentsは全系列finalのみ。resume_gatesはcheckpoint5とfinal8の系列、および独立のfinal8。
- V10は33系列が1保存step、9系列が2保存step。
  後者の`checkpoint-4`、`checkpoint-8`、`final`はstep4/8/8で、3つの異なるstepではない。
  workspace/trainerの残存payloadを数えたもので、完全な基盤モデル復元可能性の証明ではない。
- V11/V12は各明示的系列が1保存step。V11のstep16はfinal/checkpointという2役割を持つ。
- V12のstep1/4/16は`resume_from=none`の独立trial。
  task・lr1e-5・seed43でもstep1は`base_release_step=1`、step4/16は4であり、
  単一の連続訓練の古い保存とみなして捨てない。

**今回の削除は0件、容量解放は0 bytes。**
上記の基準に該当する旧stepがないことを記録したのであって、容量逼迫が解消したわけではない。

証拠: [EVIDENCE_INDEX.json](../provenance/pilots/v13_s0_s1_20260904/EVIDENCE_INDEX.json)、
[V11/V12 metadata screen](../provenance/pilots/v13_s0_s1_20260904/RETENTION_V11_V12_SCREEN.json)。
重み内容の棚卸し原本は手元の`provenance/raw/retention_20260904/`にある。
炉V10のmetadata copyは炉のV13 worktree内に保持し、inventory JSONだけ手元にも回収した。

## 今後、削除可能な旧stepが生じたとき

1. 条件・seed・系列ごとに残す2stepと削除候補の正確なpathを確定する。
2. config・source/model revision・学習/評価曲線・hash・失敗状態を保存する。
   ユーザー指定どおり、元モデルを含む生成挙動の比較記録を残してから重みを畳む。
3. 残すbundleの完全性を検証し、使用中でないことと候補のhash/statを再確認する。
4. 明示した候補だけを削除し、実際の削除結果を台帳へ記録する。
   hashは復元可能なbackupではないことを明記する。

この文書は保存規約と今回の判定であり、自動削除機能の導入ではない。
凍結済みV11/V12のconfigは過去の実行証拠なので変更していない。
次の学習用config生成では2 checkpointを保持できる保存設定を明示し、
既存の`keep_last_checkpoints=1`を新runへ無条件に引き継がない。
