# VPS 自动部署说明

> **警告：** 公开仓库中不要出现真实的 VPS 公网 IP、SSH 用户名和凭据。
> 下面的命令用 `deploy@your-vps` 作为占位符，请替换为实际部署账户。

这套方案适合低内存 VPS，不使用 Docker。

## 目标

每次本地执行 `git push` 时：

1. 本地 `.env` 先同步到 VPS 的 `/opt/a-trade/.env`
2. 代码再推到 VPS 的 bare repo
3. VPS 自动把代码更新到工作区
4. `systemd` 自动重启 `a-trade.service`

这样可以做到：

- `.env` 不进入 Git 仓库
- VPS 总是拿到最新代码和配置
- 不需要额外容器层

## 远端目录约定

以下路径是当前默认配置：

- bare repo: `/srv/git/a-trade.git`
- 工作区: `/opt/a-trade`
- 配置文件: `/opt/a-trade/.env`（权限 600，仅 `atrade` 可读）
- 真实配置: `/opt/a-trade/config/holdings.local.json` 等
- 服务名: `a-trade.service`
- 部署用户: `atrade`（非 root，sudo 仅限 `systemctl restart a-trade.service`）

## 第一步：初始化 VPS

在本机执行：

```bash
ssh deploy@your-vps 'sudo mkdir -p /opt/a-trade /srv/git'
```

然后在本机仓库里运行初始化脚本（需在本地仓库根目录）：

```bash
bash scripts/vps_install_deploy_target.sh /srv/git/a-trade.git /opt/a-trade
```

这个脚本会：

- 创建 bare repo
- 安装 `post-receive` hook
- 写入 `systemd` 服务
- 让服务开机自启

## 第二步：部署项目到 VPS

把本地仓库推到 VPS：

```bash
git remote add vps deploy@your-vps:/srv/git/a-trade.git
git push vps main
```

首次推送后，VPS 会自动把代码同步到 `/opt/a-trade`。

## 安全要点

- SSH 仅允许密钥认证，禁用密码登录。
- 仓库在 GitHub 上保持 private，或仅保留脱敏后的代码。
- 真实持仓与监控配置放在 `config/*.local.json`（Git 忽略），不在裸仓库公开。
- `QQ_BOT_APPSECRET` 不进入任何提交或公开文档；如怀疑泄露需轮换。
