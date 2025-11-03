from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import asyncio
import astrbot.api.message_components as Comp
from astrbot.api.all import command
import json
import time

from pycoingecko import CoinGeckoAPI

@register("cryptocurrency", "vmoranv", "加密货币价格查询插件", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        """初始化加密货币插件"""
        super().__init__(context)
        self.config = config if config is not None else {}
        self.cg = CoinGeckoAPI()
        
        # 设置默认配置
        self.target_currencies = self.config.get("target_currencies", ["bitcoin", "ethereum"])
        self.cooldown_period = self.config.get("cooldown_period", 300)
        self.provider_list = self.config.get("provider_list", [])
        self.rate_query_cooldown = self.config.get("rate_query_cooldown", 2)
        
        # 投资模拟相关属性
        self.investment_sessions = {}
        self.sessions_file = "investment_sessions.json"
        
        # 记录初始化信息
        logger.info(
            f"加密货币插件配置加载: target_currencies={self.target_currencies}, "
            f"cooldown_period={self.cooldown_period} 秒, "
            f"provider_list={self.provider_list}, "
            f"rate_query_cooldown={self.rate_query_cooldown}秒"
        )

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        self._load_sessions_from_file()
        self.update_task = asyncio.create_task(self.run_periodic_updates())
        self.save_task = asyncio.create_task(self._periodic_save_sessions())

    def search_coin_sync(self, query: str) -> str | None:
        """使用 CoinGecko 搜索功能查找币种 ID"""
        try:
            results = self.cg.search(query=query)
            if results and 'coins' in results and len(results['coins']) > 0:
                return results['coins'][0]['id']
            return None
        except Exception as e:
            logger.error(f"搜索币种失败: {e}", exc_info=True)
            return None
    
    def get_coin_details_sync(self, coin_id: str) -> dict | None:
        """同步方法：查询加密货币的详细信息"""
        try:
            coin_data = self.cg.get_coin_by_id(id=coin_id, localization='false', tickers='false', market_data='true', community_data='false', developer_data='false', sparkline='false')
            return coin_data
        except Exception as e:
            logger.error(f"查询币种详情失败: {e}", exc_info=True)
            return None

    def get_market_chart_sync(self, coin_id: str, days: int) -> dict | None:
        """同步方法：查询历史市场数据"""
        try:
            return self.cg.get_coin_market_chart_by_id(id=coin_id, vs_currency='usd', days=days)
        except Exception as e:
            logger.error(f"查询历史数据失败: {e}", exc_info=True)
            return None

    def get_tickers_sync(self, coin_id: str) -> dict | None:
        """同步方法：使用 get_coin_by_id 获取币种的交易对信息"""
        try:
            # pycoingecko库通过这种方式获取tickers
            return self.cg.get_coin_by_id(id=coin_id, localization='false', tickers='true', market_data='false', community_data='false', developer_data='false', sparkline='false')
        except Exception as e:
            logger.error(f"查询交易对失败: {e}", exc_info=True)
            return None

    @command("crypto")
    async def query_crypto_price(self, event: AstrMessageEvent, symbol: str = ""):
        """查询加密货币对 USD 的实时汇率和市场数据，使用格式：/crypto <币种代号>"""
        try:
            symbol = symbol.strip()
            if not symbol:
                yield event.plain_result("❌ 格式错误，请使用：/crypto <币种代号>\n例如：/crypto btc")
                return

            coin_id = await asyncio.wait_for(asyncio.to_thread(self.search_coin_sync, symbol), timeout=10.0)
            if not coin_id:
                yield event.plain_result(f"❌ 未找到币种 '{symbol}'，请检查币种代号是否正确")
                return

            coin_data = await asyncio.wait_for(asyncio.to_thread(self.get_coin_details_sync, coin_id), timeout=10.0)
            if not coin_data or 'market_data' not in coin_data:
                yield event.plain_result(f"❌ 未找到币种 '{symbol}' 的价格信息")
                return
            
            market_data = coin_data['market_data']
            name = coin_data.get('name', symbol.upper())
            coin_symbol = coin_data.get('symbol', symbol).upper()
            image_url = coin_data.get('image', {}).get('large')
            watchlist_users = coin_data.get('watchlist_portfolio_users')
            coingecko_url = f"https://www.coingecko.com/en/coins/{coin_id}"
            
            current_price = market_data.get('current_price', {}).get('usd')
            price_change_24h = market_data.get('price_change_percentage_24h')
            market_cap = market_data.get('market_cap', {}).get('usd')
            total_volume = market_data.get('total_volume', {}).get('usd')
            high_24h = market_data.get('high_24h', {}).get('usd')
            low_24h = market_data.get('low_24h', {}).get('usd')
            tvl = (market_data.get('total_value_locked') or {}).get('usd')

            def format_usd(value):
                if value is None: return "N/A"
                if value >= 1: return f"${value:,.2f}"
                return f"${value:.6f}".rstrip('0').rstrip('.')

            def format_cap(value):
                if value is None: return "N/A"
                if value > 1_000_000_000: return f"${value / 1_000_000_000:.2f}B"
                if value > 1_000_000: return f"${value / 1_000_000:.2f}M"
                return f"${value:,.2f}"

            change_icon = "📈" if (price_change_24h or 0) >= 0 else "📉"
            price_change_str = f"{price_change_24h:+.2f}%" if price_change_24h is not None else "N/A"
            watchlist_str = f"{watchlist_users:,}" if watchlist_users is not None else "N/A"

            text_result = (
                f"💰 {name} ({coin_symbol}) / USD\n"
                f"当前价格: {format_usd(current_price)}\n"
                f"24h 变化: {price_change_str} {change_icon}\n"
                f"24h 最高: {format_usd(high_24h)}\n"
                f"24h 最低: {format_usd(low_24h)}\n"
                f"总市值: {format_cap(market_cap)}\n"
                f"24h 交易量: {format_cap(total_volume)}\n"
                f"总锁仓量 (TVL): {format_cap(tvl)}\n"
                f"关注人数: {watchlist_str}\n"
                f"链接: {coingecko_url}"
            )
            
            chain = [Comp.Image.fromURL(image_url)] if image_url else []
            chain.append(Comp.Plain(text_result))
            yield event.chain_result(chain)

        except asyncio.TimeoutError:
            logger.error(f"查询 {symbol} 超时")
            yield event.plain_result("❌ 查询超时，请稍后重试")
        except Exception as e:
            logger.error(f"查询加密货币价格失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 查询失败：{str(e)}\n请稍后重试或检查网络连接")

    @command("trending")
    async def trending_coins(self, event: AstrMessageEvent):
        """获取 CoinGecko 上的热门币种"""
        try:
            trending_data = await asyncio.to_thread(self.cg.get_search_trending)
            if not trending_data or 'coins' not in trending_data:
                yield event.plain_result("❌ 无法获取热门币种列表")
                return

            coins_list = trending_data['coins']
            # 按市值排名排序，无排名的放在末尾
            sorted_coins = sorted(coins_list, key=lambda x: x['item'].get('market_cap_rank') if x['item'].get('market_cap_rank') is not None else float('inf'))

            result_lines = ["🔥 CoinGecko 热门币种 (按市值排名):\n"]
            for item in sorted_coins:
                coin = item['item']
                rank = coin.get('market_cap_rank')
                rank_str = f"#{rank}" if rank is not None else "#--"
                result_lines.append(f"{rank_str} - {coin['name']} ({coin['symbol']})")
            yield event.plain_result("\n".join(result_lines))
        except Exception as e:
            logger.error(f"获取热门币种失败: {e}", exc_info=True)
            yield event.plain_result("❌ 获取热门币种失败")

    @command("config_currencies")
    async def config_currencies(self, event: AstrMessageEvent):
        """显示当前配置的目标加密货币"""
        try:
            if not self.target_currencies:
                yield event.plain_result("❌ 未配置目标加密货币")
                return
            
            result_lines = ["📋 当前配置的目标加密货币:"]
            for currency in self.target_currencies:
                result_lines.append(f"• {currency}")
            
            yield event.plain_result("\n".join(result_lines))
        except Exception as e:
            logger.error(f"获取配置货币失败: {e}")
            yield event.plain_result("❌ 获取配置货币失败")
    
    @command("global")
    async def global_market_data(self, event: AstrMessageEvent):
        """获取全球加密货币市场数据"""
        try:
            global_data = await asyncio.to_thread(self.cg.get_global)
            if not global_data:
                yield event.plain_result("❌ 无法获取全球市场数据")
                return
            
            # API 响应有时被包裹在 'data' 键中，处理两种情况
            data = global_data.get('data') if 'data' in global_data else global_data
            if not data:
                yield event.plain_result("❌ 全球市场数据为空")
                return
            active_cryptos = data.get('active_cryptocurrencies')
            total_market_cap_usd = data.get('total_market_cap', {}).get('usd')
            market_cap_change_24h = data.get('market_cap_change_percentage_24h_usd')
            btc_dominance = data.get('market_cap_percentage', {}).get('btc')
            eth_dominance = data.get('market_cap_percentage', {}).get('eth')

            def format_cap_trillion(value):
                if value is None: return "N/A"
                return f"${value / 1_000_000_000_000:.2f}T"

            change_icon = "📈" if (market_cap_change_24h or 0) >= 0 else "📉"
            market_cap_change_str = f"{market_cap_change_24h:+.2f}%" if market_cap_change_24h is not None else "N/A"

            result = (
                f"🌍 全球加密货币市场概览\n"
                f"活跃币种数量: {active_cryptos:,}\n"
                f"总市值: {format_cap_trillion(total_market_cap_usd)}\n"
                f"24h 市值变化: {market_cap_change_str} {change_icon}\n"
                f"BTC 市值占比: {btc_dominance:.2f}%\n"
                f"ETH 市值占比: {eth_dominance:.2f}%"
            )
            yield event.plain_result(result)
        except Exception as e:
            logger.error(f"获取全球市场数据失败: {e}", exc_info=True)
            yield event.plain_result("❌ 获取全球市场数据失败")

    @command("categories")
    async def list_categories(self, event: AstrMessageEvent):
        """列出所有币种分类"""
        try:
            categories = await asyncio.to_thread(self.cg.get_coins_categories_list)
            if not categories:
                yield event.plain_result("❌ 无法获取分类列表")
                return
            
            # 限制显示数量，避免消息过长
            display_limit = 60
            limited_categories = categories[:display_limit]

            lines = ["📜 可用的币种分类 (使用 /category <id>):\n"]
            chunk_size = 3
            for i in range(0, len(limited_categories), chunk_size):
                chunk = limited_categories[i:i+chunk_size]
                lines.append(" | ".join([f"{cat['name']} (`{cat['category_id']}`)" for cat in chunk]))

            if len(categories) > display_limit:
                lines.append(f"\n(仅显示前 {display_limit} 个分类，总共 {len(categories)} 个)")

            yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error(f"获取分类列表失败: {e}", exc_info=True)
            yield event.plain_result("❌ 获取分类列表失败")

    @command("category")
    async def coins_by_category(self, event: AstrMessageEvent, category_id: str = ""):
        """获取特定分类下的币种市场数据"""
        try:
            category_id = category_id.strip()
            if not category_id:
                yield event.plain_result("❌ 请提供分类ID。使用 /categories 查看可用列表。")
                return
            coins = await asyncio.to_thread(self.cg.get_coins_markets, vs_currency='usd', category=category_id)
            if not coins:
                yield event.plain_result(f"❌ 未找到分类 '{category_id}' 的数据或该分类下没有币种。")
                return
            
            lines = [f"📊 分类 '{category_id}' Top 10 币种:\n"]
            for coin in coins[:10]:
                change_24h = coin.get('price_change_percentage_24h')
                change_icon = "📈" if (change_24h or 0) >= 0 else "📉"
                price_str = f"${coin['current_price']:,.2f}" if coin['current_price'] and coin['current_price'] >= 1 else f"${coin['current_price']:.6f}"
                change_str = f"{change_24h:+.2f}%" if change_24h is not None else "N/A"
                lines.append(f"• {coin['name']} ({coin['symbol'].upper()}): {price_str} ({change_str} {change_icon})")
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error(f"获取分类数据失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 获取分类 '{category_id}' 数据失败")

    @command("exchange")
    async def exchange_info(self, event: AstrMessageEvent, exchange_id: str = ""):
        """获取交易所信息"""
        try:
            exchange_id = exchange_id.strip()
            if not exchange_id:
                yield event.plain_result("❌ 请提供交易所ID，例如：binance")
                return
            exchange_data = await asyncio.to_thread(self.cg.get_exchanges_by_id, exchange_id)
            if not exchange_data:
                yield event.plain_result(f"❌ 未找到交易所 '{exchange_id}'")
                return

            type_str = "中心化 (CEX)" if exchange_data.get('centralized') else "去中心化 (DEX)"
            result = (
                f"🏦 交易所: {exchange_data.get('name')}\n"
                f"类型: {type_str}\n"
                f"信任排名: #{exchange_data.get('trust_score_rank', 'N/A')}\n"
                f"成立年份: {exchange_data.get('year_established', 'N/A')}\n"
                f"国家: {exchange_data.get('country', 'N/A')}\n"
                f"24h 交易量: {exchange_data.get('trade_volume_24h_btc'):,.2f} BTC"
            )
            yield event.plain_result(result)
        except Exception as e:
            logger.error(f"获取交易所信息失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 获取交易所 '{exchange_id}' 信息失败")

    @command("cry_tickers")
    async def get_tickers(self, event: AstrMessageEvent, args_str: str = ""):
        """获取币种的交易对信息。格式: /cry_tickers <币种>,[交易所ID]"""
        try:
            if not args_str.strip():
                yield event.plain_result("❌ 请提供币种代号，例如：/cry_tickers btc,binance")
                return
            
            parts = [p.strip() for p in args_str.split(',')]
            symbol = parts[0]
            exchange_id = parts[1] if len(parts) > 1 else None

            if not symbol:
                yield event.plain_result("❌ 请提供币种代号。")
                return

            coin_id = await asyncio.to_thread(self.search_coin_sync, symbol)
            if not coin_id:
                yield event.plain_result(f"❌ 未找到币种 '{symbol}'")
                return

            tickers_data = await asyncio.to_thread(self.get_tickers_sync, coin_id)
            if not tickers_data or 'tickers' not in tickers_data:
                yield event.plain_result(f"❌ 未找到 '{symbol}' 的交易对信息")
                return

            all_tickers = tickers_data['tickers']
            
            # 如果提供了交易所ID，则进行过滤
            if exchange_id:
                filtered_tickers = [t for t in all_tickers if t['market']['identifier'].lower() == exchange_id.lower()]
            else:
                filtered_tickers = all_tickers

            lines = [f"🔄 {symbol.upper()} Top 5 交易对 (USD) {'on ' + exchange_id if exchange_id else ''}:\n"]
            count = 0
            for ticker in filtered_tickers:
                if ticker.get('target') in ('USD', 'USDT'):
                    lines.append(f"• {ticker['market']['name']}: {ticker['base']}/{ticker['target']} - ${ticker['last']:,.2f} (Vol: ${ticker['converted_volume']['usd']:,.0f})")
                    count += 1
                    if count >= 5: break
            
            if count == 0:
                yield event.plain_result(f"❌ 未找到 '{symbol}' 在 {exchange_id or '任何交易所'} 的 USD/USDT 交易对")
            else:
                yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error(f"获取交易对失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 获取 '{symbol}' 交易对失败")

    @command("chart")
    async def get_sparkline_chart(self, event: AstrMessageEvent, symbol: str = ""):
        """获取币种7日价格走势图"""
        try:
            symbol = symbol.strip()
            if not symbol:
                yield event.plain_result("❌ 请提供币种代号。")
                return

            market_data = await asyncio.to_thread(self.cg.get_coins_markets, vs_currency='usd', ids=symbol.lower(), sparkline=True)
            if not market_data or 'sparkline_in_7d' not in market_data[0]:
                yield event.plain_result(f"❌ 未找到 '{symbol}' 的7日价格数据。")
                return

            prices = market_data[0]['sparkline_in_7d']['price']
            coin_name = market_data[0]['name']
            
            min_price, max_price = min(prices), max(prices)
            price_range = max_price - min_price if max_price > min_price else 1
            points = " ".join([f"{i * 4},{100 - (p - min_price) / price_range * 90}" for i, p in enumerate(prices)])
            color = "green" if prices[-1] >= prices[0] else "red"

            svg_template = f'''
            <svg width="672" height="120" xmlns="http://www.w3.org/2000/svg" style="background-color: #f0f0f0; border-radius: 8px; padding: 10px;">
                <text x="10" y="20" font-family="sans-serif" font-size="16" fill="#333">{coin_name} - 7日价格走势</text>
                <text x="662" y="35" font-family="sans-serif" font-size="12" fill="#555" text-anchor="end">最高: ${max_price:,.2f}</text>
                <text x="662" y="110" font-family="sans-serif" font-size="12" fill="#555" text-anchor="end">最低: ${min_price:,.2f}</text>
                <polyline points="{points}" fill="none" stroke="{color}" stroke-width="2"/>
            </svg>
            '''
            
            image_url = await self.html_render(svg_template, {})
            yield event.image_result(image_url)
        except Exception as e:
            logger.error(f"生成图表失败: {e}", exc_info=True)
            yield event.plain_result("❌ 生成价格图表失败。")

    @command("cry_history")
    async def get_history(self, event: AstrMessageEvent, args_str: str = ""):
        """显示币种的历史价格摘要。格式: /cry_history <币种>,[天数]"""
        try:
            if not args_str.strip():
                yield event.plain_result("❌ 请提供币种代号。格式: /cry_history <币种>,[天数]")
                return

            parts = [p.strip() for p in args_str.split(',')]
            symbol = parts[0]
            days = 7

            if not symbol:
                yield event.plain_result("❌ 请提供币种代号。")
                return

            if len(parts) > 1:
                try:
                    days = int(parts[1])
                except (ValueError, IndexError):
                    yield event.plain_result("❌ 天数必须是一个有效的数字。")
                    return
            
            if not (1 <= days <= 90):
                yield event.plain_result("❌ 天数必须在 1 到 90 之间。")
                return

            coin_id = await asyncio.to_thread(self.search_coin_sync, symbol)
            if not coin_id:
                yield event.plain_result(f"❌ 未找到币种 '{symbol}'")
                return

            chart_data = await asyncio.to_thread(self.get_market_chart_sync, coin_id, days)
            if not chart_data or 'prices' not in chart_data:
                yield event.plain_result(f"❌ 未找到 '{symbol}' 的历史数据。")
                return

            prices = [p[1] for p in chart_data['prices']]
            start_price, end_price, high_price, low_price = prices[0], prices[-1], max(prices), min(prices)
            change_percent = ((end_price - start_price) / start_price) * 100
            change_icon = "📈" if change_percent >= 0 else "📉"

            def format_usd(value):
                if value >= 1: return f"${value:,.2f}"
                return f"${value:.6f}".rstrip('0').rstrip('.')

            result = (
                f"📜 {symbol.upper()} - {days}天历史价格摘要\n"
                f"起始价格: {format_usd(start_price)}\n"
                f"结束价格: {format_usd(end_price)}\n"
                f"期间最高: {format_usd(high_price)}\n"
                f"期间最低: {format_usd(low_price)}\n"
                f"期间变化: {change_percent:+.2f}% {change_icon}"
            )
            yield event.plain_result(result)
        except Exception as e:
            logger.error(f"获取历史数据失败: {e}", exc_info=True)
            yield event.plain_result("❌ 获取历史数据失败。")

    @command("networks")
    async def get_networks(self, event: AstrMessageEvent):
        """列出 CoinGecko 支持的所有区块链网络及其原生代币"""
        try:
            platforms = await asyncio.to_thread(self.cg.get_asset_platforms)
            if not platforms:
                yield event.plain_result("❌ 无法获取支持的网络列表。")
                return
            
            lines = ["🌐 CoinGecko 支持的区块链网络:\n"]
            for platform in platforms[:20]:
                native_coin = f" (原生代币: `{platform['native_coin_id']}`)" if platform.get('native_coin_id') else ""
                lines.append(f"• {platform['name']} (`{platform['id']}`){native_coin}")
            if len(platforms) > 20:
                lines.append("\n(仅显示部分结果...)")

            yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error(f"获取网络列表失败: {e}", exc_info=True)
            yield event.plain_result("❌ 获取网络列表失败。")

    @command("gainerslosers")
    async def get_gainers_losers(self, event: AstrMessageEvent):
        """显示24小时内市场涨幅和跌幅最大的币种"""
        try:
            market_data = await asyncio.to_thread(self.cg.get_coins_markets, vs_currency='usd', order='market_cap_desc', per_page=250, page=1)
            if not market_data:
                yield event.plain_result("❌ 无法获取市场数据以计算涨跌幅榜。")
                return
            
            valid_coins = [c for c in market_data if c.get('price_change_percentage_24h') is not None]
            
            top_gainers = sorted(valid_coins, key=lambda x: x['price_change_percentage_24h'], reverse=True)
            top_losers = sorted(valid_coins, key=lambda x: x['price_change_percentage_24h'])

            lines = ["📊 24小时市场动态 (Top 250 市值)\n"]
            lines.append("📈 Top 5 涨幅榜:")
            for coin in top_gainers[:5]:
                lines.append(f"  • {coin['name']} ({coin['symbol'].upper()}): +{coin['price_change_percentage_24h']:.2f}%")
            
            lines.append("\n📉 Top 5 跌幅榜:")
            for coin in top_losers[:5]:
                lines.append(f"  • {coin['name']} ({coin['symbol'].upper()}): {coin['price_change_percentage_24h']:.2f}%")

            yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error(f"获取涨跌幅榜失败: {e}", exc_info=True)
            yield event.plain_result("❌ 获取涨跌幅榜失败。")

    @command("cry_fight")
    async def investment_simulation(self, event: AstrMessageEvent, args_str: str = ""):
        """开始或管理投资模拟"""
        try:
            logger.info(f"投资模拟命令被调用，参数: {args_str}")
            args = args_str.strip().split()
            
            if not args or args[0].lower() == "finish":
                logger.info("用户请求结束投资模拟")
                # 结算盈亏
                user_id = event.get_sender_id() if event.get_sender_id() else event.unified_msg_origin
                logger.info(f"用户标识: {user_id}")
                if user_id in self.investment_sessions:
                    session = self.investment_sessions[user_id]
                    result = await self.settle_investment(session, event)
                    yield event.plain_result(result)
                    del self.investment_sessions[user_id]
                    self._save_sessions_to_file()
                    logger.info(f"用户 {user_id} 的投资会话已成功结算并删除。")
                    return  # 确保在此处结束函数执行
                else:
                    yield event.plain_result("❌ 您没有正在进行的投资模拟")
                    return
            
            # 开始新的投资模拟
            logger.info("用户请求开始新的投资模拟")
            try:
                initial_funds = float(args[0])
                logger.info(f"起始资金: {initial_funds}")
                if initial_funds <= 0:
                    yield event.plain_result("❌ 起始资金必须大于0")
                    return
            except ValueError:
                yield event.plain_result("❌ 请输入有效的起始资金数量")
                return
            
            # 创建新的投资会话
            session = {
                "initial_funds": initial_funds,
                "current_funds": initial_funds,
                "rate_query_cooldown": self.rate_query_cooldown, # 价格更新周期
                "cooldown_period": self.cooldown_period, # AI调整周期
                "spot_positions": {},  # 现货持仓
                "futures_positions": {}, # 合约持仓
                "margin_used": 0,
                "cash": initial_funds,  # 初始资金全部为现金
                "funds_history": [],  # 资金变更记录
                "start_time": time.time(),
                "last_ai_update_time": time.time()  # 新增：上次AI更新时间
            }
            
            user_id = event.get_sender_id() if event.get_sender_id() else event.unified_msg_origin
            session["user_umo"] = event.unified_msg_origin  # 保存umo用于后续发送消息
            self.investment_sessions[user_id] = session
            self._save_sessions_to_file()
            
            # 使用AI提供商进行初始策略分析
            logger.info("开始获取AI策略分析")
            ai_analysis = await self.get_ai_strategy_analysis(event, session)
            logger.info("AI策略分析获取完成")
            
            # 根据AI策略创建初始仓位
            await self.create_initial_positions(session)
            
            result = f"🎮 投资模拟已开始\n"
            result += f"起始资金: ${initial_funds:,.2f}\n"
            result += f"当前资金: ${session['current_funds']:,.2f}\n"
            result += f"\n🤖 AI 初始策略建议:\n{ai_analysis}"
            
            yield event.plain_result(result)
        except Exception as e:
            logger.error(f"投资模拟失败: {e}", exc_info=True)
            yield event.plain_result("❌ 投资模拟启动失败")
    
    async def get_ai_strategy_analysis(self, event: AstrMessageEvent, session) -> str:
        """获取AI对投资策略的分析"""
        try:
            logger.info("开始获取AI提供商")
            # 获取AI提供商
            provider = None
            # 如果配置了提供商列表，则按顺序尝试
            if self.provider_list:
                logger.info(f"尝试使用配置的提供商列表: {self.provider_list}")
                for provider_id in self.provider_list:
                    provider = self.context.get_provider_by_id(provider_id=provider_id)
                    if provider:
                        logger.info(f"成功获取到提供商: {provider_id}")
                        break
            # 如果没有配置提供商列表或列表中的提供商都不可用，则使用当前平台的提供商
            if not provider:
                logger.info("尝试使用当前平台的提供商")
                provider = self.context.get_using_provider(umo=event.unified_msg_origin)
            # 如果仍然没有获取到提供商，则使用第一个可用的提供商
            if not provider:
                logger.info("尝试使用第一个可用的提供商")
                providers = self.context.get_all_providers()
                if providers:
                    provider = providers[0]
                    logger.info(f"使用第一个可用的提供商: {provider}")
            
            if not provider:
                logger.error("无法获取任何AI提供商")
                return "无法获取AI提供商，请检查配置"
            
            # 构建提示词
            currency_list_str = ", ".join(self.target_currencies)
            prompt = f"""
            你是一个专业的加密货币投资组合经理。用户开始了一个投资模拟，初始资金为${session['initial_funds']}。
            请根据当前市场情况，提供一个结合**现货持仓(spot)**、**合约持仓(futures)**和**现金(cash)**的综合投资策略。

            **重要规则:**
            1.  你 **必须** 从以下指定的币种列表中选择投资目标: **{currency_list_str}**。不要使用此列表之外的任何其他币种。
            2.  你的回答 **必须** 是一个严格的JSON格式，不包含任何解释性文本或代码块标记 (如 ```json)。
            3.  JSON对象必须包含以下字段: `strategy`, `risk_control`, `adjustment_strategy`, `allocation`。
            4.  `allocation` 对象必须包含 `spot_positions` (现货仓位数组), `futures_positions` (合约仓位数组), 和 `cash_percentage` (现金占总资金的百分比)。
            5.  `spot_positions` 数组中的每个对象必须包含 `coin` 和 `percentage`。
            6.  `futures_positions` 数组中的每个对象必须包含 `coin`, `percentage` (占总资金的比例), `leverage`, 和 `side` ('long' 或 'short')。
            7.  所有 `percentage` (现货、合约、现金) 的总和 **必须** 等于 100。

            **JSON格式示例:**
            {{
              "strategy": "采用核心-卫星策略，比特币和以太坊作为现货核心资产，用小部分资金进行高杠杆合约交易以博取更高收益，并保留部分现金以应对市场波动。",
              "risk_control": "现货持仓占大部分，合约保证金不超过总资金的10%。总账户止损点为15%。",
              "adjustment_strategy": "每周审查投资组合。当市场出现重大机会或风险时，动态调整现货和合约的比例。",
              "allocation": {{
                "spot_positions": [
                  {{"coin": "bitcoin", "percentage": 40}},
                  {{"coin": "ethereum", "percentage": 25}}
                ],
                "futures_positions": [
                  {{"coin": "solana", "percentage": 5, "leverage": 20, "side": "long"}}
                ],
                "cash_percentage": 30
              }}
            }}
            
            请严格遵守以上所有规则，并立即返回JSON。
            """
            
            logger.info("开始调用AI提供商的text_chat方法")
            # 请求AI分析
            llm_response = await provider.text_chat(
                prompt=prompt,
                system_prompt="你是一个专业的加密货币合约交易员和投资顾问，必须严格按照要求的JSON格式返回数据，不要使用代码块标记（如```json）"
            )
            logger.info("AI提供商调用完成")
            
            # 尝试解析AI返回的JSON数据
            try:
                # 处理可能包含在代码块中的JSON
                completion_text = llm_response.completion_text.strip()
                if completion_text.startswith("```"):
                    # 提取代码块中的内容
                    lines = completion_text.split('\n')
                    json_lines = []
                    in_json_block = False
                    for line in lines:
                        if line.startswith("```json"):
                            in_json_block = True
                            continue
                        elif line.startswith("```") and in_json_block:
                            break
                        elif in_json_block:
                            json_lines.append(line)
                    completion_text = '\n'.join(json_lines)
                
                ai_data = json.loads(completion_text)
                
                # 构造返回文本
                allocation = ai_data.get('allocation', {})
                spot_positions = allocation.get('spot_positions', [])
                futures_positions = allocation.get('futures_positions', [])
                cash_percentage = allocation.get('cash_percentage', 0)

                result = f"投资策略: {ai_data.get('strategy', 'N/A')}\n"
                result += "建议仓位配置: \n"
                if spot_positions:
                    result += "  - **现货持仓**:\n"
                    for pos in spot_positions:
                        result += f"    • {pos.get('coin', 'N/A')}: {pos.get('percentage', 0)}%\n"
                if futures_positions:
                    result += "  - **合约持仓**:\n"
                    for pos in futures_positions:
                        side_str = "做多" if pos.get('side') == 'long' else "做空"
                        result += f"    • {pos.get('coin', 'N/A')}: {pos.get('percentage', 0)}% ({side_str} @ {pos.get('leverage', 1)}x)\n"
                result += f"  - **现金**: {cash_percentage}%\n"
                result += f"风险控制: {ai_data.get('risk_control', 'N/A')}\n"
                result += f"调整策略: {ai_data.get('adjustment_strategy', 'N/A')}\n"
                
                # 保存建议仓位到会话
                session["suggested_allocation"] = allocation
                
                return result
            except json.JSONDecodeError as e:
                logger.error(f"解析AI返回的JSON数据失败: {e}")
                # 如果解析失败，返回原始文本
                return llm_response.completion_text
        except Exception as e:
            logger.error(f"获取AI策略分析失败: {e}")
            return "无法获取AI策略分析"
    
    async def settle_investment(self, session, event: AstrMessageEvent):
        """结算投资模拟"""
        try:
            # 这里可以添加更复杂的结算逻辑
            profit_loss = session["current_funds"] - session["initial_funds"]
            profit_loss_percent = (profit_loss / session["initial_funds"]) * 100
            
            result = f"📊 投资模拟结算\n"
            result += f"起始资金: ${session['initial_funds']:,.2f}\n"
            result += f"最终资金: ${session['current_funds']:,.2f}\n"
            result += f"盈亏: ${profit_loss:,.2f} ({profit_loss_percent:+.2f}%)\n"
            
            # 使用AI提供商进行总结分析
            ai_analysis = await self.get_ai_performance_analysis(event, session, profit_loss)
            result += f"\n🤖 AI 性能分析:\n{ai_analysis}"
            
            return result
        except Exception as e:
            logger.error(f"结算投资失败: {e}")
            return "结算失败"
    
    async def get_ai_performance_analysis(self, event: AstrMessageEvent, session, profit_loss) -> str:
        """获取AI对投资表现的分析"""
        try:
            # 获取AI提供商
            provider = None
            # 如果配置了提供商列表，则按顺序尝试
            if self.provider_list:
                for provider_id in self.provider_list:
                    provider = self.context.get_provider_by_id(provider_id=provider_id)
                    if provider:
                        break
            # 如果没有配置提供商列表或列表中的提供商都不可用，则使用当前平台的提供商
            if not provider:
                provider = self.context.get_using_provider(umo=event.unified_msg_origin)
            # 如果仍然没有获取到提供商，则使用第一个可用的提供商
            if not provider:
                providers = self.context.get_all_providers()
                if providers:
                    provider = providers[0]
            
            if not provider:
                return "无法获取AI提供商，请检查配置"
            
            # 构建提示词
            prompt = f"""
            你是一个专业的投资分析师。用户完成了一个合约投资模拟，初始资金为${session['initial_funds']}，
            最终资金为${session['current_funds']}，盈亏为${profit_loss}。
            请分析这次投资的表现，包括成功或失败的原因，以及未来改进建议。
            如果有资金变更记录，请结合这些记录进行分析。
            
            要求以JSON格式返回，包含以下字段：
            1. performance_summary: 性能总结（文本）
            2. profit_loss_analysis: 盈亏分析（文本）
            3. risk_control_evaluation: 风控评估（文本）
            4. improvement_suggestions: 改进建议（数组）
            5. overall_rating: 总体评分（1-10的数值）
            
            返回格式示例：
            {{
              "performance_summary": "总体表现良好",
              "profit_loss_analysis": "主要盈利来源于比特币的上涨",
              "risk_control_evaluation": "风控措施执行得当",
              "improvement_suggestions": [
                "可以适当提高以太坊的仓位比例",
                "建议在市场波动剧烈时降低杠杆"
              ],
              "overall_rating": 8
            }}
            
            请严格按照上述JSON格式返回，不要包含其他内容，不要使用代码块标记（如```json）。
            """
            
            # 请求AI分析
            llm_response = await provider.text_chat(
                prompt=prompt,
                system_prompt="你是一个专业的投资分析师，必须严格按照要求的JSON格式返回数据，不要使用代码块标记（如```json）"
            )
            
            # 尝试解析AI返回的JSON数据
            try:
                # 处理可能包含在代码块中的JSON
                completion_text = llm_response.completion_text.strip()
                if completion_text.startswith("```"):
                    # 提取代码块中的内容
                    lines = completion_text.split('\n')
                    json_lines = []
                    in_json_block = False
                    for line in lines:
                        if line.startswith("```json"):
                            in_json_block = True
                            continue
                        elif line.startswith("```") and in_json_block:
                            break
                        elif in_json_block:
                            json_lines.append(line)
                    completion_text = '\n'.join(json_lines)
                
                ai_data = json.loads(completion_text)
                
                # 构造返回文本
                result = f"总体评价: {ai_data.get('performance_summary', 'N/A')}\n"
                result += f"盈亏分析: {ai_data.get('profit_loss_analysis', 'N/A')}\n"
                result += f"风控评估: {ai_data.get('risk_control_evaluation', 'N/A')}\n"
                result += "改进建议: \n"
                for suggestion in ai_data.get('improvement_suggestions', []):
                    result += f"  - {suggestion}\n"
                result += f"总体评分: {ai_data.get('overall_rating', 'N/A')}/10\n"
                
                return result
            except json.JSONDecodeError as e:
                logger.error(f"解析AI返回的JSON数据失败: {e}")
                # 如果解析失败，返回原始文本
                return llm_response.completion_text
        except Exception as e:
            logger.error(f"获取AI性能分析失败: {e}")
            return "无法获取AI性能分析"
    
    async def create_initial_positions(self, session):
        """根据AI建议创建初始混合仓位（现货 + 合约）"""
        allocation = session.get("suggested_allocation", {})
        if not allocation:
            logger.warning("AI未提供建议仓位，将全部保留为现金")
            session["cash"] = session["initial_funds"]
            session["spot_positions"] = {}
            session["futures_positions"] = {}
            return

        spot_positions = allocation.get('spot_positions', [])
        futures_positions = allocation.get('futures_positions', [])
        cash_percentage = allocation.get('cash_percentage', 0)

        # 验证并规范化百分比总和
        total_percentage = sum(p.get('percentage', 0) for p in spot_positions) + \
                           sum(p.get('percentage', 0) for p in futures_positions) + \
                           cash_percentage

        if not (99.9 < total_percentage < 100.1) and total_percentage > 0:
            logger.warning(f"AI建议的总分配比例不为100% (实际: {total_percentage}%)，将按比例调整。")
            scale_factor = 100.0 / total_percentage
            
            for pos in spot_positions:
                pos['percentage'] *= scale_factor
            for pos in futures_positions:
                pos['percentage'] *= scale_factor
            cash_percentage *= scale_factor
            
            # 更新分配对象以反映调整
            allocation['spot_positions'] = spot_positions
            allocation['futures_positions'] = futures_positions
            allocation['cash_percentage'] = cash_percentage
        
        all_coin_ids = [p['coin'] for p in spot_positions] + [p['coin'] for p in futures_positions]
        if not all_coin_ids:
            logger.info("AI建议全仓持有现金。")
            session["cash"] = session["initial_funds"]
            return
            
        try:
            prices_data = await asyncio.to_thread(self.cg.get_price, ids=list(set(all_coin_ids)), vs_currencies='usd')
            if not prices_data:
                logger.error("无法获取初始仓位价格，模拟启动失败")
                session["cash"] = session["initial_funds"]
                return

            initial_funds = session['initial_funds']
            cash_used = 0
            margin_used = 0

            # 创建现货仓位
            for pos_info in spot_positions:
                coin_id = pos_info['coin']
                percentage = pos_info['percentage']
                price = prices_data.get(coin_id, {}).get('usd')

                if price is None or price == 0:
                    logger.warning(f"无法获取现货 {coin_id} 的价格，该仓位将跳过")
                    continue
                
                investment_amount = initial_funds * (percentage / 100)
                coin_amount = investment_amount / price
                cash_used += investment_amount

                session['spot_positions'][coin_id] = {
                    'amount': coin_amount,
                    'entry_price': price,
                    'current_price': price,
                    'value': investment_amount,
                    'pnl': 0
                }
            
            # 创建合约仓位
            for pos_info in futures_positions:
                coin_id = pos_info['coin']
                percentage = pos_info.get('percentage', 0)
                leverage = pos_info.get('leverage', 1)
                side = pos_info.get('side', 'long')
                price = prices_data.get(coin_id, {}).get('usd')

                if price is None or price == 0:
                    logger.warning(f"无法获取合约 {coin_id} 的价格，该仓位将跳过")
                    continue

                position_value = initial_funds * (percentage / 100)
                margin = position_value / leverage
                coin_amount = position_value / price
                margin_used += margin

                if side == 'long':
                    liquidation_price = price * (1 - (1 / leverage))
                else: # short
                    liquidation_price = price * (1 + (1 / leverage))

                session['futures_positions'][coin_id] = {
                    'amount': coin_amount,
                    'entry_price': price,
                    'current_price': price,
                    'value': position_value,
                    'margin': margin,
                    'leverage': leverage,
                    'side': side,
                    'liquidation_price': liquidation_price,
                    'pnl': 0
                }

            session["cash"] = initial_funds - cash_used - margin_used
            session["margin_used"] = margin_used
            session["current_funds"] = initial_funds
            logger.info(f"初始混合仓位创建完成. 现货投入: ${cash_used:.2f}, 合约保证金: ${margin_used:.2f}, 剩余现金: ${session['cash']:.2f}")

        except Exception as e:
            logger.error(f"创建初始仓位失败: {e}", exc_info=True)
            session["cash"] = session["initial_funds"]
            session["spot_positions"] = {}
            session["futures_positions"] = {}

    async def run_periodic_updates(self):
        """定期更新所有投资模拟会话"""
        while True:
            try:
                # 使用查询汇率的冷却时间作为价格更新间隔
                await asyncio.sleep(self.rate_query_cooldown)
                # 仅在有活跃的投资会话时才进行更新
                if self.investment_sessions:
                    await self.update_all_sessions()
            except asyncio.CancelledError:
                logger.info("投资模拟更新任务已取消")
                break
            except Exception as e:
                logger.error(f"定期更新投资模拟失败: {e}", exc_info=True)
                # 避免因单次错误而中断整个循环
                await asyncio.sleep(60)

    async def update_all_sessions(self):
        """更新所有活跃的投资会话"""
        user_ids = list(self.investment_sessions.keys())
        if not user_ids:
            return

        for user_id in user_ids:
            session = self.investment_sessions.get(user_id)
            if not session:
                continue
            
            spot_positions = session.get("spot_positions", {})
            futures_positions = session.get("futures_positions", {})
            
            if not spot_positions and not futures_positions:
                continue

            try:
                all_coin_ids = list(spot_positions.keys()) + list(futures_positions.keys())
                if not all_coin_ids:
                    continue

                prices_data = await asyncio.to_thread(self.cg.get_price, ids=list(set(all_coin_ids)), vs_currencies='usd')
                if not prices_data:
                    logger.warning(f"无法获取用户 {user_id} 投资组合的价格")
                    continue

                total_spot_value = 0
                
                # 更新现货仓位
                for coin_id, pos_data in spot_positions.items():
                    current_price = prices_data.get(coin_id, {}).get('usd', pos_data['current_price'])
                    pos_data['current_price'] = current_price
                    pos_data['value'] = pos_data['amount'] * current_price
                    pnl = pos_data['value'] - (pos_data['amount'] * pos_data['entry_price'])
                    pos_data['pnl'] = pnl
                    total_spot_value += pos_data['value']

                total_futures_pnl = 0
                liquidated_coins = []

                # 更新合约仓位
                for coin_id, pos_data in futures_positions.items():
                    current_price = prices_data.get(coin_id, {}).get('usd', pos_data['current_price'])
                    pos_data['current_price'] = current_price
                    
                    # 检查强平
                    if (pos_data['side'] == 'long' and current_price <= pos_data['liquidation_price']) or \
                       (pos_data['side'] == 'short' and current_price >= pos_data['liquidation_price']):
                        logger.warning(f"用户 {user_id} 的 {coin_id} {pos_data['side']} 仓位已被强平！")
                        session['margin_used'] -= pos_data['margin']
                        liquidated_coins.append(coin_id)
                        continue

                    # 计算 PnL
                    price_diff = current_price - pos_data['entry_price']
                    if pos_data['side'] == 'short':
                        price_diff = -price_diff
                    
                    pnl = price_diff * pos_data['amount']
                    pos_data['pnl'] = pnl
                    total_futures_pnl += pnl

                # 移除被强平的仓位
                for coin_id in liquidated_coins:
                    del session['futures_positions'][coin_id]

                # 计算总资产
                cash = session.get("cash", 0)
                margin_used = session.get("margin_used", 0)
                
                # 总资产 = 剩余现金 + 现货总价值 + 已用保证金 + 合约总盈亏
                session["current_funds"] = cash + total_spot_value + margin_used + total_futures_pnl
                # logger.info(f"用户 {user_id} 的投资组合已更新，当前总资金: {session['current_funds']:.2f}")

                # 检查是否需要AI进行调仓
                if time.time() - session.get("last_ai_update_time", 0) > session.get("cooldown_period", 300):
                    logger.info(f"用户 {user_id} 的投资模拟触发AI调仓...")
                    # 创建一个独立的任务来处理AI调仓，避免阻塞主更新循环
                    asyncio.create_task(self.trigger_ai_rebalance(user_id, session))
                    session["last_ai_update_time"] = time.time()

            except Exception as e:
                logger.error(f"更新用户 {user_id} 的投资模拟会话失败: {e}", exc_info=True)
    
    @command("cry_fight_status")
    async def investment_status(self, event: AstrMessageEvent):
        """查看当前投资状态"""
        try:
            user_id = event.get_sender_id() if event.get_sender_id() else event.unified_msg_origin
            if user_id not in self.investment_sessions:
                yield event.plain_result("❌ 您没有正在进行的投资模拟")
                return
            
            session = self.investment_sessions[user_id]
            
            # 重新计算当前总资金以确保数据一致性
            spot_positions = session.get("spot_positions", {})
            futures_positions = session.get("futures_positions", {})
            
            total_spot_value = sum(p.get('value', 0) for p in spot_positions.values())
            total_futures_pnl = sum(p.get('pnl', 0) for p in futures_positions.values())
            cash = session.get("cash", 0)
            margin_used = session.get("margin_used", 0)
            current_funds = cash + total_spot_value + margin_used + total_futures_pnl
            session["current_funds"] = current_funds

            # 计算总盈亏
            profit_loss = current_funds - session["initial_funds"]
            profit_loss_percent = (profit_loss / session["initial_funds"]) * 100 if session["initial_funds"] != 0 else 0
            
            result = f"📊 投资模拟状态\n"
            result += f"起始资金: ${session['initial_funds']:,.2f}\n"
            result += f"当前总资产: ${current_funds:,.2f}\n"
            result += f"总盈亏: ${profit_loss:,.2f} ({profit_loss_percent:+.2f}%)\n"
            result += f"可用现金: ${cash:,.2f}\n"
            result += "--------------------\n"

            # 显示现货持仓
            if spot_positions:
                result += "📦 **现货持仓**:\n"
                for coin_id, pos in spot_positions.items():
                    pnl = pos.get('pnl', 0)
                    entry_value = pos['amount'] * pos['entry_price']
                    pnl_percent = (pnl / entry_value) * 100 if entry_value > 0 else 0
                    result += f"  - {coin_id.capitalize()}:\n"
                    result += f"    持仓价值: ${pos['value']:,.2f}\n"
                    result += f"    未实现盈亏: ${pnl:,.2f} ({pnl_percent:+.2f}%)\n"
            else:
                result += "📦 **现货持仓**: 无\n"

            result += "--------------------\n"

            # 显示合约持仓
            if futures_positions:
                result += f"📈 **合约持仓** (保证金: ${margin_used:,.2f}):\n"
                for coin_id, pos in futures_positions.items():
                    side_str = "多头" if pos['side'] == 'long' else "空头"
                    pnl = pos.get('pnl', 0)
                    pnl_percent = (pnl / pos['margin']) * 100 if pos['margin'] > 0 else 0
                    result += f"  - {coin_id.capitalize()} ({side_str} {pos['leverage']}x):\n"
                    result += f"    开仓价: ${pos['entry_price']:,.4f}, 当前价: ${pos.get('current_price', 0):,.4f}\n"
                    result += f"    强平价: ${pos['liquidation_price']:,.4f}\n"
                    result += f"    未实现盈亏: ${pnl:,.2f} ({pnl_percent:+.2f}%)\n"
            else:
                result += "📈 **合约持仓**: 无\n"
            
            yield event.plain_result(result)
        except Exception as e:
            logger.error(f"查看投资状态失败: {e}", exc_info=True)
            yield event.plain_result("❌ 查看投资状态失败")
    
    async def get_ai_rebalance_plan(self, user_id: str, session: dict) -> dict | None:
        """获取AI对当前投资组合的调仓计划"""
        try:
            provider = self.context.get_using_provider(umo=session.get("user_umo"))
            if not provider:
                logger.error(f"无法为用户 {user_id} 获取AI提供商进行调仓")
                return None

            # 准备提供给AI的当前持仓状态
            portfolio_summary = {
                "current_total_funds": session.get("current_funds", 0),
                "available_cash": session.get("cash", 0),
                "spot_positions": [
                    {
                        "coin": coin, "amount": pos.get('amount', 0), "entry_price": pos.get('entry_price', 0),
                        "current_price": pos.get('current_price', 0), "pnl": pos.get('pnl', 0)
                    } for coin, pos in session.get("spot_positions", {}).items()
                ],
                "futures_positions": [
                    {
                        "coin": coin, "side": pos.get('side'), "leverage": pos.get('leverage'),
                        "entry_price": pos.get('entry_price', 0), "current_price": pos.get('current_price', 0),
                        "pnl": pos.get('pnl', 0), "liquidation_price": pos.get('liquidation_price', 0)
                    } for coin, pos in session.get("futures_positions", {}).items()
                ]
            }
            
            currency_list_str = ", ".join(self.target_currencies)
            prompt = f"""
            你是一个顶级的加密货币基金经理，负责管理一个动态的投资组合。
            **你的当前投资组合状态:**
            ```json
            {json.dumps(portfolio_summary, indent=2, ensure_ascii=False)}
            ```
            **你的任务:** 根据当前的市场状况和你的投资组合表现，决定是否需要进行调仓。你的目标是最大化收益，同时控制风险。
            **可用操作:** 你必须返回一个包含 `analysis` (你的决策分析) 和 `actions` (一个操作指令列表) 的JSON对象。
            `actions` 列表可以包含以下一种或多种操作:
            1. `{{ "action": "SELL_SPOT", "coin": "<coin_id>", "percentage_of_holding": <0-100> }}`: 卖出指定现货持仓的一部分或全部。
            2. `{{ "action": "CLOSE_FUTURES", "coin": "<coin_id>" }}`: 平掉指定的整个合约仓位。
            3. `{{ "action": "BUY_SPOT", "coin": "<coin_id>", "percentage_of_cash": <0-100> }}`: 使用一部分可用现金购买现货。
            4. `{{ "action": "OPEN_FUTURES", "coin": "<coin_id>", "percentage_of_cash": <1-50>, "leverage": <1-50>, "side": "<long|short>" }}`: 使用一部分可用现金作为保证金，开立新的合约仓位。
            5. `{{ "action": "HOLD", "reason": "<为什么选择不动>" }}`: 如果你认为当前仓位是最佳的，选择不进行任何操作。
            **重要规则:**
            - 所有操作的 `coin` **必须** 从这个列表中选择: `{currency_list_str}`.
            - `percentage_of_cash` 的总和不应超过100。
            - 你的回答 **必须** 是一个严格的JSON格式，不包含任何解释性文本或代码块标记。
            请立即根据当前情况返回你的决策JSON。
            """

            llm_response = await provider.text_chat(prompt=prompt, system_prompt="你是一个专业的加密货币基金经理，必须严格按照要求的JSON格式返回决策，不要使用代码块标记。")
            
            completion_text = llm_response.completion_text.strip().replace("```json", "").replace("```", "")
            plan = json.loads(completion_text)
            logger.info(f"为用户 {user_id} 获取到AI调仓计划: {plan}")
            return plan

        except Exception as e:
            logger.error(f"获取AI调仓计划失败: {e}", exc_info=True)
            return None

    async def trigger_ai_rebalance(self, user_id: str, session: dict):
        """触发AI进行调仓决策并执行"""
        logger.info(f"开始为用户 {user_id} 进行AI调仓...")
        plan = await self.get_ai_rebalance_plan(user_id, session)

        if not plan or not plan.get("actions"):
            logger.warning(f"未能获取到用户 {user_id} 的有效AI调仓计划。")
            return
            
        execution_summary = await self.execute_rebalance_plan(user_id, session, plan)

        analysis = plan.get("analysis", "无分析。")
        if execution_summary:
            message = f"🤖 **AI 投资组合调整已执行**\n\n**分析:** {analysis}\n\n**执行操作:**\n" + "\n".join(execution_summary)
            umo = session.get("user_umo")
            if umo:
                await self.context.send_message(message, umo=umo)
            else:
                logger.warning(f"无法发送AI调仓通知，因为在会话中找不到 user_umo for user {user_id}")

    async def execute_rebalance_plan(self, user_id: str, session: dict, plan: dict) -> list[str]:
        """执行AI返回的调仓计划"""
        actions = plan.get("actions", [])
        if not actions or actions[0].get("action") == "HOLD":
            return ["• AI建议保持仓位不变，未执行任何操作。"]

        execution_summary = []
        coin_ids_to_fetch = {act['coin'] for act in actions if 'coin' in act}
        prices_data = {}
        if coin_ids_to_fetch:
            try:
                prices_data = await asyncio.to_thread(self.cg.get_price, ids=list(coin_ids_to_fetch), vs_currencies='usd')
            except Exception as e:
                logger.error(f"执行调仓前获取价格失败: {e}")
                return ["• 获取最新价格失败，无法执行调仓。"]

        # 1. 首先执行所有卖出/平仓操作
        sell_actions = [act for act in actions if act.get("action") in ("SELL_SPOT", "CLOSE_FUTURES")]
        buy_actions = [act for act in actions if act.get("action") in ("BUY_SPOT", "OPEN_FUTURES")]

        for act in sell_actions:
            coin_id = act.get("coin")
            if act.get("action") == "SELL_SPOT" and coin_id in session['spot_positions']:
                pos = session['spot_positions'][coin_id]
                percentage_to_sell = act.get('percentage_of_holding', 0)
                amount_to_sell = pos['amount'] * (percentage_to_sell / 100)
                current_price = prices_data.get(coin_id, {}).get('usd', pos['current_price'])
                cash_gained = amount_to_sell * current_price
                session['cash'] += cash_gained
                pos['amount'] -= amount_to_sell
                execution_summary.append(f"• 卖出 {amount_to_sell:.6f} {coin_id.upper()} (价值 ${cash_gained:,.2f})")
                if pos['amount'] < 1e-9: del session['spot_positions'][coin_id]

            elif act.get("action") == "CLOSE_FUTURES" and coin_id in session['futures_positions']:
                pos = session['futures_positions'][coin_id]
                current_price = prices_data.get(coin_id, {}).get('usd', pos['current_price'])
                price_diff = current_price - pos['entry_price']
                if pos['side'] == 'short': price_diff = -price_diff
                pnl = price_diff * pos['amount']
                cash_returned = pos['margin'] + pnl
                session['cash'] += cash_returned
                session['margin_used'] -= pos['margin']
                del session['futures_positions'][coin_id]
                execution_summary.append(f"• 平仓 {coin_id.upper()} 合约，返还现金 ${cash_returned:,.2f} (含盈亏 ${pnl:,.2f})")

        # 2. 然后执行所有买入/开仓操作
        cash_for_investment = session['cash']
        for act in buy_actions:
            coin_id = act.get("coin")
            price = prices_data.get(coin_id, {}).get('usd')
            if not price: continue

            if act.get("action") == "BUY_SPOT":
                amount_to_invest = cash_for_investment * (act.get('percentage_of_cash', 0) / 100)
                if session['cash'] >= amount_to_invest > 0:
                    coin_amount_to_buy = amount_to_invest / price
                    session['cash'] -= amount_to_invest
                    if coin_id in session['spot_positions']:
                        pos = session['spot_positions'][coin_id]
                        new_total_cost = (pos['amount'] * pos['entry_price']) + amount_to_invest
                        pos['amount'] += coin_amount_to_buy
                        pos['entry_price'] = new_total_cost / pos['amount']
                    else:
                        session['spot_positions'][coin_id] = {'amount': coin_amount_to_buy, 'entry_price': price, 'current_price': price, 'value': amount_to_invest, 'pnl': 0}
                    execution_summary.append(f"• 使用 ${amount_to_invest:,.2f} 买入 {coin_id.upper()} 现货")

            elif act.get("action") == "OPEN_FUTURES":
                if coin_id in session['futures_positions']:
                    execution_summary.append(f"• 跳过开仓 {coin_id.upper()}: 已存在该币种的合约。")
                    continue
                margin_to_use = cash_for_investment * (act.get('percentage_of_cash', 0) / 100)
                leverage = act.get('leverage', 1)
                side = act.get('side', 'long')
                if session['cash'] >= margin_to_use > 0:
                    session['cash'] -= margin_to_use
                    session['margin_used'] += margin_to_use
                    position_value = margin_to_use * leverage
                    coin_amount = position_value / price
                    liquidation_price = price * (1 - (1 / leverage)) if side == 'long' else price * (1 + (1 / leverage))
                    session['futures_positions'][coin_id] = {'amount': coin_amount, 'entry_price': price, 'current_price': price, 'value': position_value, 'margin': margin_to_use, 'leverage': leverage, 'side': side, 'liquidation_price': liquidation_price, 'pnl': 0}
                    side_str = "多单" if side == 'long' else "空单"
                    execution_summary.append(f"• 使用 ${margin_to_use:,.2f} 保证金开立 {coin_id.upper()} {leverage}x {side_str}")
        return execution_summary

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
    def _save_sessions_to_file(self):
        """将所有投资会话保存到JSON文件"""
        try:
            with open(self.sessions_file, 'w', encoding='utf-8') as f:
                json.dump(self.investment_sessions, f, ensure_ascii=False, indent=4)
            logger.info(f"投资会话已成功保存到 {self.sessions_file}")
        except Exception as e:
            logger.error(f"保存投资会话失败: {e}", exc_info=True)

    def _load_sessions_from_file(self):
        """从JSON文件加载投资会话"""
        try:
            with open(self.sessions_file, 'r', encoding='utf-8') as f:
                self.investment_sessions = json.load(f)
            logger.info(f"投资会话已从 {self.sessions_file} 加载")
        except FileNotFoundError:
            logger.info("未找到投资会话文件，将创建一个新的会话记录")
            self.investment_sessions = {}
        except Exception as e:
            logger.error(f"加载投资会话失败: {e}", exc_info=True)
            self.investment_sessions = {}
            
    async def _periodic_save_sessions(self):
        """定期保存会话状态"""
        while True:
            await asyncio.sleep(300)  # 每5分钟保存一次
            if self.investment_sessions:
                logger.info("开始定期保存投资会话...")
                self._save_sessions_to_file()
        self._save_sessions_to_file()
        if hasattr(self, 'update_task') and self.update_task:
            self.update_task.cancel()
        if hasattr(self, 'save_task') and self.save_task:
            self.save_task.cancel()
