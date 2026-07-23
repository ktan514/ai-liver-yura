# Yura Inner State Visualizer

ゆらの感情・Drive・Activity状態を、光の粒子の色、密度、動き、形状として表示するサイドカーです。
`ai-liver-yura` モノレポの `gui/` 配下で、本体とは別プロセスとして動作します。

## 起動

```bash
cd ai-liver-yura/gui/yura-inner-state-visualizer
python3 server.py
```

ブラウザで <http://127.0.0.1:8765> を開き、その後ゆらを起動します。

```bash
cd ai-liver-yura
.venv/bin/python -m app
```

ゆらは`127.0.0.1:8766/UDP`へ状態を配信します。ビジュアライザーが起動していなくても、ゆらの動作には影響しません。

## 単独確認

別のターミナルで次を実行すると、感情状態を模擬できます。

```bash
python3 simulator.py
```

## 表現の対応

- valence: 寒色から暖色への色相
- mood: 基調色
- arousal: 粒子の速度、脈動、発光
- talkativeness: 表面の流動性
- curiosity: 全体の広がり
- engagement: 粒子の凝集度
- boredom: 形状の扁平化と散逸
- energy: 明るさと粒径

通信には入力本文、会話履歴、ウィンドウ名、キー入力を含めません。将来のPC観測機能とは別の読み取り専用境界です。
