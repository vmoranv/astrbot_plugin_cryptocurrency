# AstrBot 加密货币价格查询插件

一个功能全面的 AstrBot 加密货币查询插件，基于 CoinGecko API，提供实时价格、市场数据、历史图表、热门趋势等多种功能。

## ✨ 功能特性

-   📊 **全面的市场数据**: 查询币种价格、市值、交易量、24h高低点、TVL等。
-   🌍 **全球市场概览**: 一键获取全球加密市场总市值、活跃币种数、BTC/ETH占比等宏观数据。
-   🔥 **热门趋势追踪**: 快速了解 CoinGecko 上的热门搜索币种。
-   📈 **价格走势图**: 生成清晰的币种7日价格走势图。
-   📜 **历史数据回顾**: 获取任意币种过去1-90天的价格摘要。
-   📑 **分类市场洞察**: 按分类浏览币种，发现潜力项目。
-   🏦 **交易所信息**: 查询中心化和去中心化交易所的详细信息。
-   🚀 **涨跌幅榜**: 查看24小时内市场的涨跌幅冠军。
-   🌐 **网络/链信息**: 列出 CoinGecko 支持的所有区块链网络及其原生代币。
-   🔄 **交易对查询**: 获取指定币种在各大交易所的交易对（Tickers）信息。
-   🔍 **智能币种搜索**: 支持币种代号、全称等模糊搜索，自动匹配最相关的结果。

## 🚀 使用方法

插件提供了丰富的命令来查询不同维度的数据：

| 命令 | 功能描述 | 示例 |
| --- | --- | --- |
| `/crypto <币种>` | 查询币种的详细市场数据。 | `/crypto btc` |
| `/trending` | 获取 CoinGecko 热门币种。 | `/trending` |
| `/global` | 获取全球加密市场概览。 | `/global` |
| `/chart <币种>` | 获取币种7日价格走势图。 | `/chart solana` |
| `/cry_history <币种>,[天数]` | 获取币种历史价格摘要 (默认7天)。 | `/cry_history eth,30` |
| `/gainerslosers` | 显示24小时市场涨跌幅榜。 | `/gainerslosers` |
| `/categories` | 列出所有币种分类。 | `/categories` |
| `/category <分类ID>` | 获取特定分类下的币种。 | `/category stablecoins` |
| `/exchange <交易所ID>` | 获取交易所信息。 | `/exchange binance` |
| `/cry_tickers <币种>,[交易所]` | 获取币种的交易对信息。 | `/cry_tickers btc,binance` |
| `/networks` | 列出支持的区块链网络。 | `/networks` |

## 🪙 支持的币种

本插件通过 CoinGecko 的实时搜索 API 查询币种，因此理论上支持 CoinGecko 上市的**所有**加密货币。您可以使用币种的代号（如 `btc`）、全称（如 `bitcoin`）或部分名称进行搜索，插件会自动匹配最相关的结果。

## 🔧 技术实现

-   **API 来源**：CoinGecko Free API
-   **Python 库**：`pycoingecko`
-   **更新频率**：实时查询，数据通常在 1-5 分钟内更新

## ⚠️ 注意事项

1.  **网络连接**：需要稳定的网络连接以访问 CoinGecko API。
2.  **API 限制**：CoinGecko 免费 API 有请求频率限制，请勿过于频繁地查询。
3.  **依赖安装**：请确保已在 `requirements.txt` 中添加 `pycoingecko` 并安装。

## 📝 更新日志

### v1.0.0
-   初始版本发布。
-   实现12个核心功能，包括实时价格、全球市场、热门趋势、历史图表、分类查询、涨跌幅榜等。
-   使用 CoinGecko 实时搜索 API，支持所有上市币种。

## 📄 许可证

本项目采用 AGPL-3.0 许可证。详见 [LICENSE](LICENSE) 文件。

## 🔗 相关链接

-   [AstrBot 官方文档](https://astrbot.app)
-   [CoinGecko API 文档](https://www.coingecko.com/en/api/documentation)
-   [pycoingecko GitHub](https://github.com/man-c/pycoingecko)

## 👤 作者

vmoranv
