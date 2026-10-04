# 安全策略

## 实验代码执行

AutoResearch 默认使用 `AUTORESEARCH_EXECUTION_MODE=strict`：实验代码必须在 Docker 沙箱中运行。Docker 不可用时，系统会拒绝执行，而不会静默回退到宿主机。

仅在本地开发、且确认实验工作区可信时，才使用：

```env
AUTORESEARCH_EXECUTION_MODE=safe-local
```

不要对不可信用户输入使用 `unsafe-local`。生产环境建议保持：

```env
AUTORESEARCH_EXECUTION_MODE=strict
AUTORESEARCH_ALLOW_NETWORK=false
```

## 报告安全问题

请不要在公开 Issue 中披露可利用的安全漏洞。请通过 GitHub 私下联系仓库维护者，并提供：

- 影响版本
- 复现步骤
- 预期与实际行为
- 可能的影响范围

在修复前请避免公开传播漏洞细节。
