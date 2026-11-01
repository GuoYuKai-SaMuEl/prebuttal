<div align="center">

# Prebuttal

**在 Reviewer 2 出现之前，先回应他。**

机器学习论文的投稿前压力测试：三位相互独立的 AI 审稿人加一位领域主席（AC），使用 NeurIPS / ICLR / ICML / ARR / CVPR 的真实审稿表。

[English](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/README.md) · 简体中文 · [繁體中文](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/README.zh-TW.md)

[**网站**](https://guoyukai-samuel.github.io/prebuttal/zh-cn/) ·
[**示例报告**](https://guoyukai-samuel.github.io/prebuttal/reports/sample.html) ·
[更新日志](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/CHANGELOG.md)

</div>

> 这是精简版文档，完整内容以[英文 README](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/README.md)为准；工具输出和审稿表都是英文。

## 快速上手

```bash
pip install prebuttal          # 或 pipx install prebuttal、uv tool install prebuttal

prebuttal check paper.pdf --venue cvpr      # 直接拒稿检查：几秒钟、免费、无需模型
prebuttal run paper.pdf --venue cvpr        # 完整的模拟审稿
prebuttal run paper.zip --venue cvpr        # Overleaf：Menu → Download → Source
prebuttal run ./latex-src/ --venue iclr     # LaTeX 项目文件夹，无需编译
prebuttal run https://arxiv.org/abs/2510.12345 --venue neurips
```

需要 Python 3.11 及以上。`prebuttal backends` 会列出你当前可用的模型；如果一个都没有，它会告诉你最快的办法（通常是 `prebuttal key set gemini`，使用免费的 Gemini key）。内置会议：`neurips`、`iclr`、`icml`、`acl`（ARR）、`cvpr`；其他会议或期刊可以用 `prebuttal venues new` 自定义。

## 投稿前：`prebuttal check`

无需模型、不花钱，针对会导致直接拒稿（desk reject）的问题做确定性检查：

- **匿名**：PDF 元数据里的作者姓名、第一页的邮箱、camera-ready 或 NeurIPS
  `[preprint]` 版本、致谢部分、自己的代码仓库链接、“our previous work [12]”。
- **格式**：正文超过页数限制（包括双栏排版），缺少 NeurIPS checklist / ICML impact
  statement / CVPR LLM usage statement / ARR limitations 等必需章节。
- **残留**：未解析的 `??` 交叉引用、`[?]` 文献引用、TODO，以及肉眼看不到的隐藏文字。

LaTeX 项目无需编译即可检查（页数限制需要 PDF）。发现可能导致直接拒稿的问题时，退出码为 6。每年的规定都会变，输出会列出每条规则的出处，请对照当年的投稿须知。

如果论文放在 GitHub 上，也可以每次 push 自动检查，不需要任何 secrets：

```yaml
- uses: GuoYuKai-SaMuEl/prebuttal@v0.5.4
  with:
    paper: paper/      # LaTeX 文件夹、主 .tex、.zip 或编译好的 PDF
    venue: cvpr
```

## 模拟审稿：`prebuttal run`

| 角色 | 风格 |
|---|---|
| R1 `senior_kind` | 资深、建设性，关注核心贡献和主要问题 |
| R2 `adversarial` | 传说中的 Reviewer 2：动机、baseline、创新性、夸大结论 |
| R3 `detail_obsessive` | 逐格看表格：统计、消融实验、可复现性 |
| AC `area_chair` | 汇总意见、裁决分歧、估计最终分数、写修改清单 |

三位审稿人在相互独立的上下文中阅读论文，可以各用不同的模型（Claude × Codex × Gemini…），所以结论确实会不同，分歧（σ）也一定会列出来。每条意见都必须引用证据（章节、表格、数字）。

每份报告开头是 AC 整理的**修改清单**（must / should / could）。改完后加上 `--note "改了什么"` 重新运行（seed 默认不变），再用 `prebuttal diff` 查看哪些问题还在、哪些已经解决。单次运行的分数波动常常只是噪声，不一定是修改带来的。

## 支持哪些模型

| 后端 | 认证 | 说明 |
|---|---|---|
| `agent-claude` / `agent-codex` | 你的 Claude / Codex 订阅，**无需 API key** | 不提供任何能读文件或执行命令的工具 |
| `api-gemini` | `GEMINI_API_KEY` | 有**免费额度** |
| `api-openrouter` | `OPENROUTER_API_KEY` | `:free` 模型免费 |
| `api-openai` / `api-anthropic` | 自带 key | |
| `ollama` | 无需 | 本地运行，论文不会离开你的电脑 |
| `relay` | 无需 | 由你、你的 agent 的子代理或任何系统来回答 |

`--dry-run` 会先列出计划和预估费用，不调用任何模型。

## 隐私与诚实

- **论文内容会发送给你选择的后端服务商**，之后如何处理（存储、训练、人工审阅）由该服务商的条款决定。Prebuttal 不运营任何服务器，也看不到你的论文。免费额度通常以你的数据为代价；未发表的论文请先确认条款、改用付费方案，或用 `ollama`、`relay` 留在本地。
- 运行记录保存在 `~/.prebuttal/`，API key 保存在 `~/.prebuttal/keys.env`，只有你的账户能读取；没有任何遥测。
- **这是压力测试，不是预测**：与 OpenReview 真实评分的校准结果还没有发布，请把每个分数都当作未经校准的数字。
- 使用前请留意各会议对 AI 的规定：用 AI 准备自己的论文由你决定；用 AI 审别人的论文则必须遵守该会议的披露规定。

## 更多

[完整英文文档](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/README.md)：配置文件、自定义会议、推理强度（effort）、让审稿人看图、运行记录与项目、在 coding agent 中使用、校准脚本。

MIT 许可。Prebuttal 是独立项目，与 NeurIPS、ICLR、ICML、ACL/ARR、CVPR 或任何模型服务商均无关联。
