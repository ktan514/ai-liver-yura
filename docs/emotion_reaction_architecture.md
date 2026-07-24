# 感情表現・反応生成アーキテクチャ

## 1. 目的

本設計は、ゆらの内部感情を出来事から更新し、その状態をCharacter LLMが会話文脈・関係性・活動状況と統合して、発話・声・表情・動作へ変換するための責務境界を定める。

感情値と外部表現は分離する。怒りが高いことは必ず怒鳴ることを意味せず、悲しみが高いことは必ず泣くことを意味しない。Character LLMは、感情を見せる、隠す、我慢する、声や間だけに漏らす、複数感情を混ぜる、といった表現方法を判断する。

## 2. 基本原則

- 感情状態の更新権限はCoreに置く。
- Character LLMは感情状態を解釈するが、内部状態を直接変更しない。
- 自然文の意味評価と、感情状態の確定的な更新処理を分離する。
- ユーザーが表明した感情と、ゆら自身に生じた感情を区別する。
- 「怒ってみて」などの演技要求と、実際の感情変化を区別する。
- CoreはTTS、Live2D、その他の表現Pluginがなくても成立する。
- 出力の正規形式はReactionPlanとし、ReactionSegment単位で発話、表情、動作、音声意図、間を保持する。

## 3. 処理フロー

```text
AgentEvent
  -> StimulusContextBuilder
  -> EmotionAppraiser
  -> EmotionAppraisal
  -> EmotionStateUpdater
  -> EmotionState / EmotionHistory
  -> EmotionContextBuilder
  -> ResponseContext
  -> Character LLM
  -> ReactionPlan
  -> Voice / Expression / Gesture Plugin
```

## 4. 感情状態

既存のmood、arousal、valence、talkativenessは互換情報として維持しつつ、短期反応感情を個別の連続値として保持する。

```text
joy
amusement
anger
sadness
fear
surprise
discomfort
emotional_pressure
```

各値は0.0以上1.0以下とする。moodは直接保存する主状態ではなく、個別感情値と補助値から導出する要約値として扱う。

複数感情は同時に存在できる。例えば、信頼する相手に傷つけられた場合はangerとsadnessが同時に上昇し得る。

## 5. EmotionAppraisal

EmotionAppraisalは、出来事がゆらに与えた変化候補を表す。最低限、以下を保持する。

- 個別感情のdelta
- arousal、valence、talkativenessのdelta
- 原因カテゴリ
- 原因の要約
- 対象
- source_event_id
- confidence

システム事実は決定的なルールで評価できる。ユーザー入力やコメントの意味評価は専用Emotion Appraisal Modelへ委譲できるが、発話生成は行わせない。

## 6. EmotionStateUpdater

EmotionStateUpdaterは次を担当する。

- delta適用
- 値域制限
- 感情ごとの減衰
- emotional_pressureの蓄積と解放
- arousal、valence、talkativenessの再計算
- moodの導出
- 急激で不自然な反転の抑制

感情ごとに減衰速度を変える。surpriseは速く、angerは中程度、sadnessは比較的ゆっくり減衰する。

## 7. EmotionContext

Character LLMへはEmotionStateの現在値だけでなく、次の情報を渡す。

- current
- dominant_emotions
- mixed_emotions
- delta
- causes
- duration
- emotional_pressure
- recent_history
- expression_tendency

expression_tendencyは表現を固定する命令ではなく、隠しやすさ、声へ漏れる可能性、強い表出の可能性などを示す傾向値とする。

## 8. Character LLMの責務

Character LLMは、EmotionContext、会話文脈、関係性、Character Profile、Activity、利用可能な表現チャネルを統合し、ReactionPlanを生成する。

内部感情を必ずそのまま表面化させる必要はない。原因と矛盾しない範囲で、冷静に振る舞う、照れて隠す、言葉に詰まる、後から感情が漏れる、といった表現を選べる。

## 9. 演技要求と実感情の分離

- 「怒った演技をして」「悲しそうに読んで」は表現要求として扱い、内部感情を原則変更しない。
- 侮辱、喪失、称賛、予想外の知らせなどはEmotion Appraisalを経由して内部感情を変更する。
- 管理者用の状態注入は専用デバッグ経路とし、一般ユーザー入力やviewerコメントから実行できない。

## 10. Plugin境界

Coreが生成するのは高レベルの表現意図までとする。

```text
expression="restrained_anger"
voice_intent.style="subdued"
gesture="look_away"
```

Voice PluginとLive2D Pluginは、高レベル意図を各エンジン固有のパラメータへ変換する。Pluginが存在しない場合でも、Coreの感情更新とCharacter応答生成は継続できなければならない。

## 11. テスト方針

以下を独立して検証する。

1. 状態注入による各感情の表現確認
2. 通常イベントからの自然な感情発生
3. 演技要求と内部感情変化の分離
4. 感情混在
5. 関係性・公開状況による表出差
6. 感情ごとの減衰と回復
7. ReactionPlanのセグメント実行
8. Plugin不在時のCore継続動作
