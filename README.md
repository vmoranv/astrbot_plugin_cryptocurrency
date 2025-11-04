# AstrBot 加密货币插件 2.0

一个功能全面且具备高级AI投资模拟能力的 AstrBot 插件，基于 CoinGecko API，提供实时价格、市场数据、历史图表，以及一个由AI驱动的、具备完整交易和风控能力的投资模拟器。

## ✨ 功能特性

-   📊 **全面的市场数据**: 查询币种价格、市值、交易量、24h高低点、TVL等。
-   🌍 **全球市场概览**: 一键获取全球加密市场总市值、活跃币种数、BTC/ETH占比等宏观数据。
-   🔥 **热门趋势追踪**: 快速了解 CoinGecko 上的热门搜索币种。
-   📈 **价格走势图**: 生成清晰的币种7日价格走势图。
-   📜 **历史数据回顾**: 获取任意币种过去1-90天的价格摘要。
-   📑 **分类市场洞察**: 按分类浏览币种，发现潜力项目。
-   🏦 **交易所信息**: 查询中心化和去中心化交易所的详细信息。
-   🚀 **涨跌幅榜**: 查看24小时内市场的涨跌幅冠军。

---

### 🎮 **核心功能：高级AI投资模拟器**

本插件最核心的功能是一个高度真实的AI投资模拟器，它不仅仅是简单的买卖，而是一个由AI扮演基金经理的完整交易生态系统。

-   **🤖 动态AI决策**: AI会根据实时市场状况和现有投资组合的表现，自主决定交易策略。
-   **💼 复合投资组合**: AI能够同时管理**现货(Spot)**、**合约(Futures)**和**现金(Cash)**，构建复杂的投资策略。
-   **🔪 全功能交易指令**: AI具备执行多种专业交易操作的能力：
    -   **现货交易**: `买入 (BUY_SPOT)` / `卖出 (SELL_SPOT)`
    -   **合约交易**: `开多 (OPEN_LONG)` / `开空 (OPEN_SHORT)` / `平仓 (CLOSE_LONG/SHORT)`
    -   **仓位管理**: `增加/减少保证金 (ADD/REDUCE_MARGIN)` / `提高/降低杠杆 (INCREASE/DECREASE_LEVERAGE)`
    -   **风险管理**: `设置止损 (SET_STOP_LOSS)` / `设置止盈 (SET_TAKE_PROFIT)`
-   **🛡️ 健壮的执行引擎**:
    -   **多层验证**: 所有AI指令在执行前都会经过严格的参数、风险和前提条件验证。
    -   **事务性执行**: 一系列AI操作要么全部成功，要么在任何一步失败时全部回滚，确保账户状态的绝对安全。
    -   **实时通知**: 当AI执行调仓或触发止损/止盈订单时，用户会收到实时通知。

## 🚀 使用方法

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
| `/config_currencies` | 显示当前配置的目标加密货币。 | `/config_currencies` |

---

### **投资模拟专用命令**

| 命令 | 功能描述 | 示例 |
| --- | --- | --- |
| `/cry_fight <起始资金>` | 使用指定的起始资金开始一个新的投资模拟。 | `/cry_fight 10000` |
| `/cry_fight finish` | 结束当前模拟，平掉所有仓位并进行详细结算。 | `/cry_fight finish` |
| `/cry_fight_status` | 查看当前投资组合的详细状态和盈亏。 | `/cry_fight_status` |


## 🔧 技术实现

-   **核心逻辑**: `main.py` - 插件主逻辑、命令处理和AI决策流程。
-   **金融计算**: `investment_utils.py` - 封装了所有核心的金融计算函数，如盈亏(PnL)、强平价格、总资产等，确保计算的准确性和可维护性。
-   **AI响应解析**: `ai_parser.py` - 包含一个强大的解析器，负责清理、验证和规范化AI返回的JSON数据，通过预定义的Schema确保AI指令的可靠性。
-   **API 来源**：CoinGecko Free API (`pycoingecko`库)
-   **健壮性设计**: 采用事务性操作、多层验证和标准化的 `OperationResult` 返回对象，确保系统在处理复杂AI指令时的稳定性和安全性。

## 📝 更新日志

### v2.0.0
-   **AI能力全面升级**: 投资模拟器中的AI现已具备管理杠杆、调整保证金、设置止损/止盈等高级能动性。
-   **引入健壮的执行引擎**: 为所有AI操作建立了多层验证（参数、风险、前提）和事务性执行机制，失败时可安全回滚。
-   **代码架构重构**: 将核心的金融计算和AI响应解析逻辑分别拆分到 `investment_utils.py` 和 `ai_parser.py` 中，提高了代码的可读性和可维护性。
-   **关键Bug修复**: 彻底修复了合约盈亏（PnL）和强平价格计算中的严重逻辑错误。
-   **优化AI交互**: 引入基于Schema的AI响应验证器，大幅提高了处理AI返回数据的可靠性。

### v1.0.0
-   初始版本发布。
-   实现14个核心查询功能。
-   新增基础版的AI投资模拟功能。

## 📄 许可证

本项目采用 AGPL-3.0 许可证。详见 [LICENSE](LICENSE) 文件。

## 🔗 相关链接

-   [AstrBot 官方文档](https://astrbot.app)
-   [CoinGecko API 文档](https://www.coingecko.com/en/api/documentation)
-   [pycoingecko GitHub](https://github.com/man-c/pycoingecko)

## 👤 作者

vmoranv
