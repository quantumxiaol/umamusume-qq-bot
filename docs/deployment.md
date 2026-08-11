# 部署与运维

推荐架构是服务器只运行 QQ Bot，Agent 使用 Hugging Face Space：

```text
QQ Gateway → 服务器上的 QQ Bot → Hugging Face Agent
                         ↓
                  data/bot.sqlite3
```

## 环境变量

```env
AppID=你的QQ机器人AppID
AppSecret=你的QQ机器人AppSecret

UMAMUSEME_AGENT_URL=https://quantumxiaol-umamusume-agent.hf.space
UMAMUSEME_AGENT_API_ACCESS_KEY="与后端 API_ACCESS_KEY 相同的值"

BOT_DATABASE_PATH=data/bot.sqlite3
LOCAL_HISTORY_MAX_MESSAGES=1000
AGENT_TIMEOUT_SECONDS=600
CHARACTERS_CACHE_TTL_SECONDS=300
LOG_LEVEL=INFO
```

兼容的 Agent 变量别名：

- `UMAMUSUME_AGENT_URL`
- `AGENT_BASE_URL`
- `UMAMUSUME_AGENT_API_ACCESS_KEY`
- `AGENT_API_ACCESS_KEY`

## 安装

```bash
cd /root/servers/umamusume-qq-bot
uv sync --frozen --no-dev
mkdir -p logs data
```

先以前台方式验证：

```bash
.venv/bin/umamusume-qq-bot
```

使用直接入口不会保留 `uv run` 父进程，更适合低内存服务器。

## systemd

创建 `/etc/systemd/system/umamusume-qq-bot.service`：

```ini
[Unit]
Description=Umamusume QQ Bot
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/servers/umamusume-qq-bot
ExecStart=/root/servers/umamusume-qq-bot/.venv/bin/umamusume-qq-bot

Restart=always
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=20
UMask=0077

Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

启用：

```bash
systemctl daemon-reload
systemctl enable --now umamusume-qq-bot
systemctl status umamusume-qq-bot
```

管理：

```bash
systemctl restart umamusume-qq-bot
systemctl stop umamusume-qq-bot
systemctl start umamusume-qq-bot
```

## 日志

Bot 自身日志：

```bash
tail -f /root/servers/umamusume-qq-bot/logs/bot.log
```

systemd 日志：

```bash
journalctl -u umamusume-qq-bot -n 100 --no-pager
journalctl -u umamusume-qq-bot -f
```

`logs/bot.log` 每个文件最多 5 MB，并保留 5 个备份。日志包含用户标识与输入正文，应限制访问。

QQ Gateway 可能返回 `4009 Session timed out`。随后出现“机器人重连成功”即表示 SDK 已自动恢复，
不需要重启服务。

## SQLite 数据

默认路径：

```text
data/bot.sqlite3
```

SQLite 使用 WAL，因此运行时还可能看到：

```text
bot.sqlite3-wal
bot.sqlite3-shm
```

备份前建议短暂停止 Bot，然后复制整个目录：

```bash
systemctl stop umamusume-qq-bot
cp -a data data-backup-$(date +%F)
systemctl start umamusume-qq-bot
```

Docker 部署时必须把整个 `data` 目录挂载到持久卷。只保留容器内文件无法抵抗容器重建。

## 更新

```bash
cd /root/servers/umamusume-qq-bot
git pull --ff-only
uv sync --frozen --no-dev
systemctl restart umamusume-qq-bot
systemctl status umamusume-qq-bot
```

## 资源占用

直接启动的 Bot 实测常驻内存约 33–40 MB。SQLite 不需要独立进程，仅增加少量连接与页缓存。
服务器有约 300 MB 空闲内存时，无需改写为 Go。

