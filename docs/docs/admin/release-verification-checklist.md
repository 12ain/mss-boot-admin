---
title: Admin 发布与部署验证清单
order: 28
nav:
  order: 1
  title: admin
description: 完整 Thin Host 业务发行前后的最小验证清单
keywords: [admin release checklist smoke regression]
---

## 使用方式

:::warning
v1.3.5 与 v1.3.6 都已永久停止为不可变部分发布；本清单不能授权补发其缺失制品。
v1.3.7 已完成 Distribution 公共对账并成为当前稳定版，但本清单不能把后续源码提交冒充为
v1.3.7 制品。安装与升级从[快速开始](/getting-started)进入。
Docs 是异步、非阻断的网站发布；`docs/v*` 只标识网站部署，其缺失或失败不影响组件、npm、
GitHub Latest、current stable 或采用状态。
:::

本清单区分 Foundation 发布检查与业务 Thin Host 的生产部署巡检。代码先经 PR 合并到
`main`，同一完整 commit 的 main 流水线通过后创建对应组件 Tag。Tag 流水线直接构建和
发布该 commit 的制品；Root Tag 自动启动官方 npm 发布，等待同一 commit 的 main 与
组件 Tag 流水线成功后，通过 Trusted Publishing 发布 npm，并在身份对账后更新 GitHub
Latest。新版本不再要求额外 Root preview、手工 stable promotion 或人工环境审批。
Docs 从独立文档 Tag 发布，不加入上述依赖图。v1.3.7 使用过的旧流程仅保留在历史发布记录中。

## 一、发布前检查

### 构建检查

- [ ] PR 的相关检查通过；改动已合并到 `main`，发布使用同一完整 commit
- [ ] main 流水线和组件 Tag 流水线均成功，失败时先修复并重新验证，不能用本地记录替代失败的流水线
- [ ] 受影响页面完成桌面、窄屏、深链和刷新验收，控制台及失败网络请求可解释
- [ ] 外部 Thin Host 兼容性检查通过，脱敏报告可追溯到对应 commit
- [ ] Tag 流水线生成的 Root 工具、包、SBOM、校验和及镜像身份完整；正式发布不依赖额外预演制品
- [ ] Admin Tag 流水线在 Framework 已公开后，以 `GOWORK=off` 和公共 Go Proxy 解析精确 Framework
- [ ] 后端和 Admin Web 依赖精确为同一个协调版本，锁文件无漂移
- [ ] Root Tag 启动的 npm 流水线已等到 main 与相关 Tag 流水线成功；npm 版本、`gitHead`、完整性、provenance 及 `latest` 已对账
- [ ] GitHub Latest 在 npm 对账成功后更新；公共制品对账完成后再更新 `currentStableVersion`
- [ ] 使用者文档继续以 `currentStableVersion` 为安装与升级基线，`nextPublicVersion` 只用于候选说明；Docs 网站状态单独记录

`mss verify --changed` 与 `mss verify --all` 仍可用于本地定位和预先验证，不能替代上述
main/Tag 检查结果，也不另设人工发布审批。

### 核心能力检查

- [ ] 登录成功且首次登录状态正常
- [ ] Welcome 页监控卡片与趋势图正常
- [ ] 日志页面能看到登录日志、审计日志、运行时日志
- [ ] 仅在显式 Local 开发 Delivery 中执行头像上传 smoke，并确认 `/public/uploads/{uuid}` 内容一致；该结果不作为生产 Provider 证据
- [ ] 当 Local/S3-compatible 仍为 Legacy / Blocked 时，生产 ingress 已阻断两个上传路径，且未授予通用 `storage:upload` 权限作为纵深防御；头像入口没有独立 Casbin permission
- [ ] 告警规则可以保存
- [ ] 已启用任务状态正常
- [ ] 国际化接口可返回有效语言资源

## 二、发布后冒烟检查

- [ ] `/healthz` 正常
- [ ] 前端首页可打开
- [ ] WebSocket 在线状态正常
- [ ] `/public/` 未被当作生产对象 Delivery 代理，两个上传入口仍被部署侧阻断
- [ ] 后端日志无持续性 fatal 错误

## 三、异常归属建议

| 现象 | 优先排查 |
|------|----------|
| 前端空白页 | 前端构建、代理、接口鉴权 |
| 监控图表无数据 | `/admin/api/monitor` 的 `collectedAt`/`stale`/`instanceId`、内置系统作业日志、登录态 |
| 头像入口被禁用 | 当前 Provider / Delivery evidence 状态、ingress 与权限门禁；不要通过临时开放 `/public/` 绕过 |
| 告警不发送 | 通知配置、规则状态、日志输出 |
| 用户任务未执行 | `task.enable`、cron 表达式、任务状态、TaskRun |
| 内置监控/会话清理未执行 | task server 启动日志和系统作业错误；不要以 Task/TaskRun 无记录判定失败 |

## 三-A、Docs 网站异步候补（不阻断发布）

- [ ] 仅在准备发布网站时检查 `docs/v*` 身份；该 Tag 只表示网站发布，不是 Distribution Tag
- [ ] Docs Tag 指向已存在 Root Release commit 或其受审 merged-main 后代；更新时先删同名 Release，再删 Tag，确认均不存在后同名重建，禁止 force-update
- [ ] Docs 源来自受审 merged-main，受保护部署、替换 Release、归档校验和和 `release.json` 身份一致
- [ ] 在内置浏览器刷新首页与嵌套路由，检查可见版本、控制台和失败网络请求
- [ ] 若任一项失败，记录“网站部署待办”并只修复 Docs；不得阻止或回退 Framework、Admin、Admin Web、Root、镜像、npm、GitHub Latest、`currentStableVersion` 或采用路径

## 四、回滚前确认

- [ ] 问题是否来自配置而非代码
- [ ] 数据库结构是否发生变化
- [ ] 若开发环境曾显式启用 Local，已有 opaque-key 对象是否已保留；不要回滚到解析后限流或 user/filename key
- [ ] 日志目录是否需要保留
- [ ] 通知渠道凭据是否改动

## 推荐阅读

- [集成测试指南](/admin/integration-test-guide)
- [v1.3.5 不可变部分发布记录](/releases/v1-3-5)
- [v1.3.6 不可变部分发布记录](/releases/v1-3-6)
- [v1.3.7 稳定版说明](/releases/v1-3-7)
- [v1.3.7 快速开始](/getting-started)
