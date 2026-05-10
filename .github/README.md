# 爱股票 → 飞书推送服务

自动从爱股票抓取重点要闻，推送到飞书群机器人。

## 功能

- 每5分钟轮询爱股票快讯API
- 智能过滤：仅推送 `important=yes` 或 `app_push=yes` 的要闻
- 增量去重：已推送的不再重复
- 飞书消息卡片：带颜色标记、详情链接
- **关机也能推送**：部署到GitHub Actions，7×24小时运行

## 快速开始

### 第一步：创建飞书机器人

1. 打开飞书 → 进入目标群聊 → 点击群设置 → 「机器人」→「添加机器人」→「自定义机器人」
2. 设置机器人名称（如"爱股票要闻"）
3. 复制 Webhook URL（格式：`https://open.feishu.cn/open-apis/bot/v2/hook/xxx`）
4. 安全策略选择「签名校验」（推荐）或「自定义关键词」

### 第二步：本地测试

```bash
# 设置环境变量
set FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/你的hook

# 测试模式（仅查看，不推送）
python aigupiao_feishu_push.py --test

# 单次推送
python aigupiao_feishu_push.py --once

# 持续运行（本地7×24小时）
python aigupiao_feishu_push.py --continuous
```

### 第三步：部署到GitHub Actions（关机也能推送）

1. 在GitHub创建新仓库（如 `aigupiao-feishu-push`）
2. 上传本项目文件
3. 进入仓库 Settings → Secrets and variables → Actions → New repository secret
   - Name: `FEISHU_WEBHOOK_URL`
   - Value: 你的飞书Webhook URL
4. GitHub Actions 会自动每5分钟运行一次

## 配置说明

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `FEISHU_WEBHOOK_URL` | (必填) | 飞书机器人Webhook地址 |
| `FILTER_MODE` | `important` | 过滤模式：`important`/`all`/`app_push`/`hot` |
| `FETCH_NUMBER` | `20` | 每次获取条数 |
| `GITHUB_CACHE_PATH` | (自动) | GitHub Actions缓存路径 |

### 过滤模式说明

| 模式 | 说明 | 预计频率 |
|------|------|---------|
| `important` | important=yes 或 app_push=yes | 约5-15条/天 |
| `app_push` | 仅 app_push=yes（最核心） | 约3-8条/天 |
| `hot` | 24h热评 + important + app_push | 约10-20条/天 |
| `all` | 所有快讯 | 约50-100条/天 |

## 飞书消息效果

推送的消息卡片包含：
- 🔴 **重要推送**（app_push=yes）→ 红色标题
- 🟠 **重要**（important=yes）→ 橙色标题
- 📰 **要闻** → 蓝色标题
- 内容摘要 + 查看详情按钮

## 数据源

API: `https://apis.aigupiao.com/Express/express_list/`
- 无需登录
- 无需API Key
- 返回JSON格式快讯数据

## 故障排除

| 问题 | 解决方案 |
|------|---------|
| 飞书收不到消息 | 检查Webhook URL是否正确；检查飞书机器人是否被移除 |
| GitHub Actions不运行 | 确认仓库不是空仓库；Actions需要至少一次提交后才会启用定时任务 |
| 推送重复 | 删除 `push_state.json` 重新初始化；检查cache是否正常 |
| 收到太多消息 | 将 `FILTER_MODE` 改为 `app_push` |
