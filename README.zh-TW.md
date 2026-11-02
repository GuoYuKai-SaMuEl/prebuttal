<div align="center">

# Prebuttal

**在 Reviewer 2 出現之前，先回答他。**

機器學習論文的投稿前壓力測試：三位互相獨立的 AI 審稿人加上一位領域主席（AC），使用 NeurIPS / ICLR / ICML / ARR / CVPR 的真實審稿表單。

[English](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/README.md) · [简体中文](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/README.zh-CN.md) · 繁體中文

[**網站**](https://guoyukai-samuel.github.io/prebuttal/zh-tw/) ·
[**使用指南（英文）**](https://guoyukai-samuel.github.io/prebuttal/guide/) ·
[**範例報告**](https://guoyukai-samuel.github.io/prebuttal/reports/sample.html) ·
[更新紀錄](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/CHANGELOG.md)

</div>

> 這是精簡版說明。每個指令與設定的完整說明在[使用指南（英文）](https://guoyukai-samuel.github.io/prebuttal/guide/)；工具的輸出與審稿表單都是英文。

## 快速開始

```bash
pip install prebuttal          # 或 pipx install prebuttal、uv tool install prebuttal

prebuttal check paper.pdf --venue cvpr      # 直接退稿檢查：幾秒鐘、免費、不用模型
prebuttal run paper.pdf --venue cvpr        # 完整的模擬審稿
prebuttal run paper.zip --venue cvpr        # Overleaf：Menu → Download → Source
prebuttal run ./latex-src/ --venue iclr     # LaTeX 專案資料夾，不需編譯
prebuttal run https://arxiv.org/abs/2510.12345 --venue neurips
```

需要 Python 3.11 以上。`prebuttal backends` 會列出你目前能用哪些模型；如果一個都沒有，它會告訴你最快的方法（通常是 `prebuttal key set gemini`，用免費的 Gemini key）。內建會議：`neurips`、`iclr`、`icml`、`acl`（ARR）、`cvpr`；其他會議或期刊可以用 `prebuttal venues new` 自訂。

## 投稿前：`prebuttal check`

不用模型、不花錢，針對會讓論文被直接退稿（desk reject）的問題做確定性的檢查：

- **匿名**：PDF 中繼資料裡的作者名字、第一頁的 e-mail、camera-ready 或 NeurIPS
  `[preprint]` 版本、致謝段落、自己的 repo 連結、「our previous work [12]」。
- **格式**：正文超過頁數上限（含雙欄排版），缺少 NeurIPS checklist / ICML impact
  statement / CVPR LLM usage statement / ARR limitations 等必要章節。
- **殘留**：未解析的 `??` 參照、`[?]` 文獻引用、TODO，以及人眼看不到的隱藏文字。

LaTeX 專案不需編譯即可檢查（頁數上限需要 PDF）。找到可能被直接退稿的問題時，exit code
為 6。每年的規定都會變，輸出會列出每條規則的出處，請對照當年的投稿須知。

論文放在 GitHub 上的話，也可以每次 push 都自動檢查，不需要任何 secrets：

```yaml
- uses: GuoYuKai-SaMuEl/prebuttal@v0.5.4
  with:
    paper: paper/      # LaTeX 資料夾、主 .tex、.zip 或編譯好的 PDF
    venue: cvpr
```

## 模擬審稿：`prebuttal run`

| 角色 | 個性 |
|---|---|
| R1 `senior_kind` | 資深、建設性，抓核心貢獻與主要疑慮 |
| R2 `adversarial` | 傳說中的 Reviewer 2：動機、baseline、新穎性、過度宣稱 |
| R3 `detail_obsessive` | 逐格讀表格：統計、ablation、可重現性 |
| AC `area_chair` | 整合意見、裁決分歧、估計最終分數、寫修改清單 |

三位審稿人在互相獨立的情境下閱讀論文，可以各自用不同模型（Claude × Codex × Gemini…），所以結論真的會不同，分歧（σ）也一定會列出來。每項意見都必須引用證據（章節、表格、數字）。

每份報告開頭是 AC 整理的**修改清單**（must / should / could）；如果是你自己的稿子，直接退稿檢查找到的問題會排在清單最前面（標記為 `check`），AC 也會知道。改完之後加上 `--note "改了什麼"` 重跑（seed 預設不變），再用 `prebuttal diff` 看哪些問題還在、哪些不見了。單次執行的分數變動常常只是雜訊，不一定是修改造成的。

## 用哪些模型

| 後端 | 認證 | 說明 |
|---|---|---|
| `agent-claude` / `agent-codex` | 你的 Claude / Codex 訂閱，**不需 API key** | 不給任何能讀檔或執行指令的工具 |
| `api-gemini` | `GEMINI_API_KEY` | 有**免費額度** |
| `api-openrouter` | `OPENROUTER_API_KEY` | `:free` 模型免費 |
| `api-openai` / `api-anthropic` | 自備 key | |
| `ollama` | 不需要 | 本機執行，論文不會離開你的電腦 |
| `relay` | 不需要 | 由你、你的 agent 的子代理或任何系統回答 |

`--dry-run` 會先列出計畫與預估費用，不呼叫任何模型。

## 隱私與誠實

- **論文內容會送到你選的後端供應商**，之後怎麼處理（保存、訓練、人工檢視）由該供應商的條款決定。Prebuttal 不經營任何伺服器，也看不到你的論文。免費額度通常以你的資料作為代價；未發表的論文請確認條款、改用付費方案，或用 `ollama`、`relay` 留在本機。
- 執行紀錄存在 `~/.prebuttal/`，API key 存在 `~/.prebuttal/keys.env`，都只有你的帳號能讀取；沒有任何遙測。
- **這是壓力測試，不是預言**：與 OpenReview 真實評分的校準結果還沒發表，請把每個分數都當成未校準的數字。
- 使用前請留意各會議對 AI 的規定：用 AI 準備自己的論文由你決定；用 AI 審別人的論文則必須遵守該會議的揭露規範。

## 更多

[使用指南（英文）](https://guoyukai-samuel.github.io/prebuttal/guide/)：設定檔的每個選項、自訂會議、推理強度（effort）、讓審稿人看圖、執行紀錄與專案、在 coding agent 裡使用、完整指令表。

各會議的投稿檢查清單（英文）：[NeurIPS](https://guoyukai-samuel.github.io/prebuttal/venues/neurips/) · [ICLR](https://guoyukai-samuel.github.io/prebuttal/venues/iclr/) · [ICML](https://guoyukai-samuel.github.io/prebuttal/venues/icml/) · [ARR](https://guoyukai-samuel.github.io/prebuttal/venues/acl/) · [CVPR](https://guoyukai-samuel.github.io/prebuttal/venues/cvpr/)

MIT 授權。Prebuttal 是獨立專案，與 NeurIPS、ICLR、ICML、ACL/ARR、CVPR 或任何模型供應商均無關聯。
