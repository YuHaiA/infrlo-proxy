# Infrlo proxy

个人 VLESS WebSocket 服务，使用官方 Xray 内核，提供带令牌验证的 Clash/Mihomo 和 V2Ray 订阅。

## 部署

- Build Command: `python3 build.py`
- Run Command: `python3 app.py`
- 应用监听 `0.0.0.0:$PORT`；没有 `PORT` 时使用 8080。
- 使用平台提供的 HTTPS 应用域名，由平台负责入口 TLS。Xray 只监听容器内部回环地址。

在平台的 Environment Variables 中设置：

| 变量 | 含义 |
| --- | --- |
| `VLESS_UUID` | 随机 UUID，用于节点身份验证，必须设置 |
| `SUB_TOKEN` | 至少 24 字符的随机订阅令牌，必须设置 |
| `PUBLIC_HOST` | 平台分配的公开域名，不含 `https://` 或路径 |
| `PORT` | Infrlo 应用配置返回的 HTTP 端口，本实例为 `5000`，需要显式设置 |
| `WS_PATH` | 可选，默认 `/vless` |
| `EXTRA_NODES_B64` | 可选，将 `{"clash": [...], "v2ray": [...]}` 的 UTF-8 JSON 转为 Base64，用于合并已有节点，推荐在 Infrlo 上使用 |
| `EXTRA_NODES_JSON` | 可选的原始 JSON 格式；设置 `EXTRA_NODES_B64` 时优先使用 Base64 配置 |

保存变量后重启或重新部署。认证信息缺失时不会开放代理。

Infrlo 当前的 Python 构建环境提供 `python3`，没有 `python` 命令。控制台显示 `running` 或 `Deployment Successful` 后，仍需检查 `/health` 是否返回 HTTP 200。

使用单一构建脚本完成依赖安装和 Xray 下载，避免平台将 `&&` 后的命令执行到构建容器之外。

Base64 用于避免 JSON 引号及节点 URI 特殊字符影响平台传递环境变量；它不是加密，配置中仍包含节点凭据。

## 使用

- 健康检查：`https://<域名>/health`，正常返回 `ok`。
- Clash/Mihomo：`https://<域名>/clash?token=<SUB_TOKEN>`。
- V2Ray：`https://<域名>/v2ray?token=<SUB_TOKEN>`。
- VLESS 使用 WebSocket、TLS、443 端口，SNI 和 WebSocket Host 均为平台域名。
- WebSocket 路径默认为 `/vless`。

项目不包含部署密钥。不要把环境变量、运行目录或实际订阅链接提交到 GitHub。

平台必须支持 WebSocket 转发。普通 HTTPS 应用入口不能直接承载 Telegram 的 MTProto TCP 代理；Telegram 可使用手机代理客户端提供的 VPN 网络。

## 内核

安装脚本固定 Xray `v26.3.27`，仅从 XTLS 官方 GitHub 发布下载，并验证发布文件 SHA-256。
