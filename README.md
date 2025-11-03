# AstrBot 加密货币价格查询插件

一个基于 AstrBot 的加密货币实时价格查询插件，支持查询数百种加密货币对 USDT 的实时汇率。

## ✨ 功能特性

- 🔍 **实时价格查询**：查询加密货币对 USDT 的实时汇率
- 📊 **多种币种支持**：支持查询 CoinGecko API 中的所有加密货币
- 🎯 **智能识别**：支持币种缩写（如 `btc`）和全称（如 `bitcoin`）
- 💰 **价格格式化**：自动格式化价格显示，大额币种显示 2 位小数，小额币种显示更多精度
- ⚡ **快速响应**：基于 CoinGecko 免费 API，无需 API 密钥

## 🚀 使用方法

### 基本用法

在聊天中发送以下命令：

```
/crypto 币种代号
```

### 使用示例

```
/crypto btc          # 查询比特币价格
/crypto ethereum     # 查询以太坊价格（使用全称）
/crypto sol          # 查询 Solana 价格
/crypto bitcoin      # 查询比特币价格（使用全称）
```

### 响应示例

```
💰 BTC / USDT
当前价格: $43,450.12 USDT
```

## 🪙 支持的币种

插件内置了常见币种的缩写映射，包括但不限于：

| 缩写 | 全称 | CoinGecko ID |
|------|------|--------------|
| btc | Bitcoin | bitcoin |
| eth | Ethereum | ethereum |
| bnb | Binance Coin | binancecoin |
| sol | Solana | solana |
| ada | Cardano | cardano |
| dot | Polkadot | polkadot |
| doge | Dogecoin | dogecoin |
| xrp | Ripple | ripple |
| matic | Polygon | matic-network |
| ltc | Litecoin | litecoin |
| trx | Tron | tron |
| avax | Avalanche | avalanche-2 |
| link | Chainlink | chainlink |
| atom | Cosmos | cosmos |
| etc | Ethereum Classic | ethereum-classic |

**注意**：除了上述内置映射的币种，你也可以使用任何 CoinGecko 支持的币种 ID（小写）。查看完整的币种列表：[CoinGecko API](https://www.coingecko.com/en/api/documentation)

## 🔧 技术实现

- **API 来源**：CoinGecko Free API
- **Python 库**：pycoingecko
- **更新频率**：实时查询，数据通常在 1-5 分钟内更新

## ⚠️ 注意事项

1. **网络连接**：需要稳定的网络连接以访问 CoinGecko API
2. **API 限制**：CoinGecko 免费 API 有请求频率限制，请勿频繁查询
3. **币种 ID**：如果使用币种全称查询失败，请尝试使用 CoinGecko 的币种 ID（通常为小写的币种名称）
4. **依赖安装**：如果插件提示 `pycoingecko 未安装`，请运行 `pip install pycoingecko` 安装依赖

## 🐛 故障排除

### 问题：插件加载失败，提示 `ModuleNotFoundError: No module named 'pycoingecko'`

**解决方案**：
```bash
pip install pycoingecko
```

### 问题：查询币种时提示"未找到币种"

**可能原因**：
- 币种代号输入错误
- 币种在 CoinGecko 中不存在

**解决方案**：
- 检查币种代号拼写
- 尝试使用币种全称（如 `bitcoin` 而不是 `BTC`）
- 访问 [CoinGecko](https://www.coingecko.com/) 确认币种是否存在

### 问题：查询失败，提示网络错误

**解决方案**：
- 检查网络连接
- 稍后重试（可能是 CoinGecko API 临时不可用）

## 📝 更新日志

### v1.0.0
- 初始版本发布
- 支持查询加密货币对 USDT 的实时价格
- 支持常见币种缩写和全称识别

## 📄 许可证

本项目采用 AGPL-3.0 许可证。详见 [LICENSE](LICENSE) 文件。

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 🔗 相关链接

- [AstrBot 官方文档](https://astrbot.app)
- [CoinGecko API 文档](https://www.coingecko.com/en/api/documentation)
- [pycoingecko GitHub](https://github.com/man-c/pycoingecko)

## 👤 作者

YourName

## 📮 支持

如有问题或建议，请通过以下方式联系：
- 提交 [Issue](../../issues)
- 查看 [AstrBot 帮助文档](https://astrbot.app)

---

**免责声明**：本插件提供的数据仅供参考，不构成任何投资建议。加密货币投资有风险，请谨慎决策。
