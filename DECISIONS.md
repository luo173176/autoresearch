
## D-032 M8 双入口研究模式（2026-10-07）

将“文献来源”和“研究方式”解耦：自动检索和用户导入都写入同一 papers/projects_papers/chunks 管线；新增 research_runs 持久化研究历史。`mode=auto` 使用固定的研究问题、方法、发现、局限、空白框架；`mode=custom` 使用用户提供的键值框架问题，并要求至少一项。PDF 上传只保存到服务端生成的 data/papers/{paper_id}.pdf 路径，文件名不直接参与路径拼接；LLM 失败或关闭时返回带 chunk 证据引用的规则草稿。
