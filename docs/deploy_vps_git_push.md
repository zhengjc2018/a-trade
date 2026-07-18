# VPS 自动部署说明

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
- 配置文件: `/opt/a-trade/.env`
- 服务名: `a-trade.service`

## 第一步：初始化 VPS

在本机执行：

```bash
ssh root@96.30.194.21 'mkdir -p /opt/a-trade /srv/git'
```

然后在本机仓库里运行初始化脚本：

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
git remote add vps root@96.30.194.21:/srv/git/a-trade.git
git push vps main
```

首次推送后，VPS 会自动把代码同步到 `/opt/a-trade`。

然后在 VPS 上创建虚拟环境并安装依赖：

```bash
ssh root@96.30.194.21 '
cd /opt/a-trade &&
python3 -m venv .venv &&
./.venv/bin/pip install --upgrade pip wheel setuptools &&
./.venv/bin/pip install -r requirements.txt
'
```

再启动服务：

```bash
ssh root@96.30.194.21 'systemctl start a-trade.service'
```

## 第三步：同步 `.env`

本地先确保 `.env` 已经存在并填写好真实配置。

然后安装本地 `pre-push` hook：

```bash
bash scripts/install_pre_push_env_sync.sh root@96.30.194.21 /opt/a-trade/.env
```

安装后，每次你执行：

```bash
git push vps main
```

会先发生这件事：

- 本地 `.env` 被拷贝到 VPS 的 `/opt/a-trade/.env`
- 文件权限被设为 `600`
- 远端 `a-trade.service` 先重启一次

然后再继续执行正常的代码推送。

## 如何检查服务是否启动

最直接的检查命令：

```bash
ssh root@96.30.194.21 'systemctl is-active a-trade.service'
```

结果含义：

- `active`：服务正常运行
- `activating`：仍在启动或重启
- `failed`：启动失败

看更完整状态：

```bash
ssh root@96.30.194.21 'systemctl status --no-pager a-trade.service'
```

看最近日志：

```bash
ssh root@96.30.194.21 'journalctl -u a-trade.service -n 50 --no-pager'
```

## 常用排障

### 1. `No module named 'atrade'`

说明 `systemd` 没有把项目根目录加入 `PYTHONPATH`。

当前服务已经按下面方式修正：

- `WorkingDirectory=/opt/a-trade`
- `Environment=PYTHONPATH=/opt/a-trade`

如果你手动改过服务文件，改完后执行：

```bash
ssh root@96.30.194.21 'systemctl daemon-reload && systemctl restart a-trade.service'
```

### 2. `.env` 没同步到 VPS

检查本地 hook 是否安装：

```bash
ls -l .git/hooks/pre-push
```

如果没有，重新安装：

```bash
bash scripts/install_pre_push_env_sync.sh root@96.30.194.21 /opt/a-trade/.env
```

### 3. 依赖安装失败

确认 VPS 上能访问 PyPI，并且 `requirements.txt` 已包含正确依赖。

当前项目使用：

- `qq-botpy`
- `apscheduler`
- `pandas`
- `numpy`
- `requests`
- `python-dotenv`
- `loguru`
- `websockets`

## 推荐使用方式

以后你的日常更新流程就是：

```bash
git add .
git commit -m "your message"
git push vps main
```

push 时会自动同步 `.env` 和代码，然后 VPS 自动重启服务。
