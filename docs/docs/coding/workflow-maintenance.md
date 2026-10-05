---
title: 流水线维护与职责
order: 4
description: v1.3.8 准备期间的工作流必要性审计、保留职责与重复执行清理
---

# 流水线维护与职责

本次审计以 2026-10-05 的 `main` 提交
`65eb485a34a4940407fde2b5bf4e5329077091a9`（PR #596）及远端分支保护为基线。
以下是各工作流的职责；具体触发条件以 `.github/workflows/` 中的实现为准。
发布动作遵循经审查合入的 `.mss/release-policy.yaml`，本页不另设发布批准条件。

## 分支保护与故障处理

远端 `main` 要求 `guard / guard`、`govulncheck`、`Analyze (go)`、
`Analyze (actions)` 和 `admin-ci`；同时启用严格最新分支检查、至少一名审查者、
Code Owners 审查及管理员约束。路径过滤不能使这些必需上下文永久缺失。

PR #596 合并后的 [Docs 构建失败](https://github.com/mss-boot-io/mss-boot-admin/actions/runs/37239426821)
和 [外部 Thin Host 兼容检查失败](https://github.com/mss-boot-io/mss-boot-admin/actions/runs/37239427171)
涉及不同职责，均保留并修复。失败本身不是删除检查的依据。

PR #597 合并后，这两条检查已通过。后续 main 检查还暴露了仅在合并后运行的
元数据问题：Go 校验和刷新必须保留 Go 的语义版本排序并清理旧组件版本；
历史升级演练应隔离 `go.work.sum` 的自动写入，而不是放宽执行后的源码干净检查。
应用模板的依赖清单和锁文件也必须一起更新，在替换本地测试 tarball、重新解析依赖前
先验证冻结锁文件，避免外部消费者测试掩盖模板漂移。

## 全部工作流的必要性

| 文件 | 决定 | 保留职责或删除依据 |
| --- | --- | --- |
| `ci.yml` | 保留，去重 | 必需 `admin-ci`；Admin 普通测试及合并后 race、coverage、模块图、独立 Go 消费者和构建。Admin/shared 全包测试已覆盖 `admin/compatibility`，额外该包测试仅在 framework 范围运行。 |
| `pr-guard.yml` | 保留 | 必需 PR 治理上下文及 API、配置、迁移、工作流的文档约束。 |
| `component-scope.yml` | 保留 | 被多个工作流调用，统一范围路由；没有独立运行记录是复用模式的正常行为。 |
| `codeql.yml` | 保留 | Go 和 Actions 静态安全分析是必需检查，周期扫描能发现未改代码的新问题。 |
| `govulncheck.yml` | 保留 | 必需 Go 漏洞检查；按所属模块扫描，并定期检查新披露漏洞。 |
| `mss-boot-ci.yml` | 保留 | Framework 在 `GOWORK=off` 下独立测试；合并后增加 race、coverage 和模块边界。 |
| `admin-distribution-compatibility.yml` | 保留并修复 | 安装真实打包前端、生成外部 Thin Host、验证组合及浏览器行为，覆盖仓库内部单测无法证明的使用方式。 |
| `agent-native-ci.yml` | 保留手动诊断 | 托管环境的 Agent 契约诊断及 macOS/Windows 可移植性；不自动重复日常 PR 检查。 |
| `frontend-v6-ci.yml` | 保留手动诊断 | 托管环境依赖、打包、构建、浏览器完整诊断；不自动重复日常 PR 检查。 |
| `pat-migration-integration.yml` | 保留 | MySQL/PostgreSQL 凭据哈希、OAuth 密码和身份迁移；普通无数据库测试无法替代。 |
| `theme-settings-integration.yml` | 保留 | MySQL/PostgreSQL 新装与升级 schema、MySQL 排序规则下保留键处理。 |
| `v0.7-upgrade-integration.yml` | 保留 | 从真实历史 v0.7 schema 连续升级两次，覆盖 SQLite/MySQL/PostgreSQL；与单条迁移测试不同。 |
| `docs.yml` | 保留并修复 | 网站依赖审计、构建和独立 Docs 标签部署。 |
| `swagger.yml` | 保留 | 生成并核验 OpenAPI，发布独立 GitHub Pages API 文档，不等同于产品 Docs 网站。 |
| `container.yml` | 保留 | Root 镜像构建和标签发布；发布方式由已合入策略规定。 |
| `release.yml` | 保留 | Root 二进制、归档、SBOM、校验和与 GitHub Release 的唯一发布职责。 |
| `framework-release.yml` | 保留 | Framework 模块标签及独立公开 Go 模块身份。 |
| `admin-release.yml` | 保留 | Admin 模块标签及公开 Framework 依赖解析，区别于仓库内 workspace 测试。 |
| `frontend-v6-release.yml` | 保留 | 前端 tarball、镜像、GitHub Packages 和组件 Release。 |
| `npm-release.yml` | 保留 | 官方 npm 的 OIDC 发布及精确包身份核对；不引入长期 npm token。 |
| `scorecard.yml` | 保留 | 周期性供应链及分支保护审计；已不随每次 main push 运行。 |
| `mirror.yml` | 保留 | 成功执行实际 Gitee 仓库镜像，是分发服务，不是重复测试；纯 Docs 改动不触发。 |
| `issue-triage.yml` | 保留 | 在具体 issue 创建、编辑、重开时归类及提示缺失信息，按事件运行。 |
| `weekly-digest.yml` | 删除 | 只创建汇总 issue，不验证软件，也不是任何分支保护或发布依赖；现有周报未形成处理闭环。 |

删除周报的证据是 W24–W39 共 16 条自动 issue 全部仍为 OPEN 且无评论，
包括[最近一期 #589](https://github.com/mss-boot-io/mss-boot-admin/issues/589)。
调用的共享模板按有限数量的 API 结果计数，并仍要求记录到已经整合的旧
`mss-boot-docs/aigc` 路径。去掉自动周报后，Actions 页面、PR 检查和具体 issue
继续保留原始记录；已有 issue 保持不变。

远端 Actions 还显示 GitHub 托管的 Dependabot Updates、Dependency Graph 和自动代码
审查。这些不是本仓库工作流文件：依赖更新和依赖图服务继续提供依赖维护信息，自动审查
提供补充意见，均不能代替必需检查。本次未更改 GitHub 应用或仓库级服务设置。

## 标签内构建与自动 npm 发布

发布流水线从同一个已合入 `main` 且检查成功的提交开始，依次处理 Framework、Admin、
前端和 Root 标签。前端标签构建并上传一次 `frontend-v6-dist`，发布 job 只使用同次运行的
结果；Root 直接下载该前端 Release 的现成资产。Root 镜像也在自己的标签运行中构建和
发布，不再依赖另一次手动 preview。

Root 标签自动启动官方 npm 工作流。只读 job 等待相同提交的 main 检查及五条组件/Root
标签工作流全部成功，然后受保护 job 通过 OIDC 发布已经生成的 tarball。无需额外的
手动 preview 或单独批准稳定晋升的 PR；合并源、版本不可变、包校验和、来源身份和
`latest` 不倒退仍然验证。成功发布后再通过普通文档 PR 记录稳定版事实。

瞬时失败应重跑同次运行中的失败 job，保留成功构建的原始字节。不要全量重建后覆盖已公开
的镜像或包；若源代码需要修复且已有核心制品公开，应使用新的补丁版本。

## 维护与验证

评估重复工作时应比较边界：workspace 单测、公开 Go Proxy 解析、打包安装和真实数据库
升级不是同一种检查。手动诊断工作流本身不会产生例行运行费用，不为减少文件数量删除其
独立故障定位能力。安全扫描、必需检查、公开包身份和实际服务分发也不能用别的绿灯替代。

修改后运行 `python3 -m unittest tools.release.test_workflow_governance` 和
`go run ./cmd/mss verify --changed`，文档使用 `pnpm --dir docs build`。
提交 PR 后检查实际 Actions 运行，只有对应新提交的结果才证明修复有效；历史失败记录
不需要删除，旧提交重跑也不能验证新代码。
