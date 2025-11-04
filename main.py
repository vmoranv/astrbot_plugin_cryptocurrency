from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context, Star, StarTools
from astrbot.api import logger
import asyncio
import astrbot.api.message_components as Comp
from astrbot.api.all import command
import json
import time

import copy
from .investment_utils import (calculate_futures_pnl,
                               calculate_liquidation_price, calculate_total_assets,
                               check_position_risk, calculate_total_margin_usage_ratio,
                               calculate_coin_exposure, calculate_minimum_margin)
from .ai_parser import (AIResponseParser, STRATEGY_SCHEMA,
                        REBALANCE_SCHEMA, PERFORMANCE_SCHEMA)

from pycoingecko import CoinGeckoAPI

class OperationResult:
    """统一操作返回格式"""
    def __init__(self, success: bool, message: str, data: dict = None):
        self.success = success
        self.message = message
        self.data = data or {}

class MyPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        """初始化加密货币插件"""
        super().__init__(context)
        self.config = config if config is not None else {}
        self.cg = CoinGeckoAPI()
        self.ai_parser = AIResponseParser()
        
        # 定义操作的必需参数
        self.ACTION_REQUIREMENTS = {
            "BUY_SPOT": ["coin", "percentage_of_cash"],
            "SELL_SPOT": ["coin", "percentage_of_holding"],
            "OPEN_LONG": ["coin", "percentage_of_cash", "leverage"],
            "OPEN_SHORT": ["coin", "percentage_of_cash", "leverage"],
            "CLOSE_LONG": ["coin"],
            "CLOSE_SHORT": ["coin"],
            "ADD_MARGIN": ["coin", "percentage_of_cash"],
            "REDUCE_MARGIN": ["coin", "percentage_of_margin"],
            "INCREASE_LEVERAGE": ["coin", "new_leverage"],
            "DECREASE_LEVERAGE": ["coin", "new_leverage"],
            "SET_STOP_LOSS": ["coin", "stop_price"],
            "SET_TAKE_PROFIT": ["coin", "target_price"],
            "HOLD": [],
        }
        
        # 设置默认配置
        self.target_currencies = self.config.get("target_currencies", ["bitcoin", "ethereum", "solana"])
        self.cooldown_period = self.config.get("cooldown_period", 300)
        self.provider_list = self.config.get("provider_list", [])
        self.rate_query_cooldown = self.config.get("rate_query_cooldown", 2)
        
        # 投资模拟相关属性
        self.investment_sessions = {}
        data_dir = StarTools.get_data_dir("cryptocurrency")
        data_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_file = data_dir / "investment_sessions.json"
        
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

    # --- Investment Simulation Core ---

    @command("cry_fight")
    async def investment_simulation(self, event: AstrMessageEvent, args_str: str = ""):
        """开始或管理投资模拟"""
        try:
            args = args_str.strip().split()
            user_id = event.get_sender_id() if event.get_sender_id() else event.unified_msg_origin

            if not args or args[0].lower() == "finish":
                if user_id in self.investment_sessions:
                    session = self.investment_sessions[user_id]
                    result = await self.settle_investment(session, event)
                    yield event.plain_result(result)
                    del self.investment_sessions[user_id]
                    self._save_sessions_to_file()
                else:
                    yield event.plain_result("❌ 您没有正在进行的投资模拟")
                return
            
            try:
                initial_funds = float(args[0])
                if initial_funds <= 0:
                    yield event.plain_result("❌ 起始资金必须大于0")
                    return
            except ValueError:
                yield event.plain_result("❌ 请输入有效的起始资金数量")
                return
            
            session = {
                "initial_funds": initial_funds,
                "current_funds": initial_funds,
                "rate_query_cooldown": self.rate_query_cooldown,
                "cooldown_period": self.cooldown_period,
                "spot_positions": {},
                "futures_positions": {},
                "pending_orders": [], # 新增：用于存放止损等挂单
                "margin_used": 0,
                "cash": initial_funds,
                "funds_history": [],
                "start_time": time.time(),
                "last_ai_update_time": time.time(),
                "user_umo": event.unified_msg_origin,
                "user_id": user_id
            }
            self.investment_sessions[user_id] = session
            
            ai_analysis_text = await self.get_ai_strategy_analysis(event, session)
            await self.create_initial_positions(session)
            self._save_sessions_to_file()
            
            result = (f"🎮 投资模拟已开始\n"
                      f"起始资金: ${initial_funds:,.2f}\n"
                      f"当前资金: ${session['current_funds']:,.2f}\n\n"
                      f"{ai_analysis_text}")
            yield event.plain_result(result)
        except Exception as e:
            logger.error(f"投资模拟失败: {e}", exc_info=True)
            yield event.plain_result("❌ 投资模拟启动失败")

    async def settle_investment(self, session, event: AstrMessageEvent):
        """结算投资模拟，包含平仓所有头寸和详细的盈亏分析"""
        try:
            logger.info(f"开始为用户 {session.get('user_id')} 结算投资...")
            # 1. 获取所有持仓币种的最新价格
            all_coin_ids = list(session.get("spot_positions", {}).keys()) + list(session.get("futures_positions", {}).keys())
            prices_data = {}
            if all_coin_ids:
                prices_data = await asyncio.to_thread(self.cg.get_price, ids=list(set(all_coin_ids)), vs_currencies='usd')

            # 2. 计算平仓后的最终现金
            final_cash = session.get("cash", 0)
            spot_pnl_total = 0
            futures_pnl_total = 0

            # 模拟平掉所有现货仓位
            for coin_id, pos in session.get("spot_positions", {}).items():
                price = prices_data.get(coin_id, {}).get('usd', pos.get('current_price', pos['entry_price']))
                position_value = pos['amount'] * price
                final_cash += position_value
                spot_pnl_total += position_value - (pos['amount'] * pos['entry_price'])

            # 模拟平掉所有合约仓位
            for coin_id, pos in session.get("futures_positions", {}).items():
                price = prices_data.get(coin_id, {}).get('usd', pos.get('current_price', pos['entry_price']))
                pnl = calculate_futures_pnl(pos, price)
                cash_returned = pos['margin'] + pnl
                final_cash += cash_returned
                futures_pnl_total += pnl

            # 3. 计算最终财务数据
            initial_funds = session["initial_funds"]
            final_funds = final_cash
            total_pnl = final_funds - initial_funds
            total_pnl_percent = (total_pnl / initial_funds) * 100 if initial_funds != 0 else 0

            # 4. 构建结算报告
            result = (f"📊 **投资模拟结算**\n\n"
                      f"**最终资产明细:**\n"
                      f"  - 起始资金: ${initial_funds:,.2f}\n"
                      f"  - 最终资金: ${final_funds:,.2f}\n"
                      f"  - **总盈亏: ${total_pnl:,.2f} ({total_pnl_percent:+.2f}%)**\n\n"
                      f"**盈亏来源分析:**\n"
                      f"  - 现货交易盈亏: ${spot_pnl_total:,.2f}\n"
                      f"  - 合约交易盈亏: ${futures_pnl_total:,.2f}\n")
            
            # 5. 获取AI性能分析
            ai_analysis = await self.get_ai_performance_analysis(event, session, final_funds, total_pnl, total_pnl_percent)
            result += f"\n🤖 **AI 性能分析**\n{ai_analysis}"
            
            return result
        except Exception as e:
            logger.error(f"结算投资失败: {e}", exc_info=True)
            return "❌ 结算失败，发生内部错误。"

    # --- AI Interaction & Logic ---

    async def _get_ai_provider(self, event: AstrMessageEvent = None, session: dict = None):
        """获取可用的AI Provider。优先从 session 恢复，其次从 event 获取，最后回退。"""
        provider = None
        
        # 优先级1: 从 session 中使用 provider_id 恢复 provider (最安全)
        if session and (provider_id := session.get("provider_id")):
            provider = self.context.get_provider_by_id(provider_id=provider_id)
            if provider: return provider

        # 优先级2: 从 event 中获取当前 provider (用于会话初始化)
        if event and (umo := event.unified_msg_origin):
            provider = self.context.get_using_provider(umo=umo)
            if provider: return provider

        # 回退逻辑1: 从配置的 provider 列表中查找
        if self.provider_list:
            for provider_id in self.provider_list:
                provider = self.context.get_provider_by_id(provider_id=provider_id)
                if provider: return provider
        
        # 回退逻辑2: 获取第一个可用的 provider
        providers = self.context.get_all_providers()
        if providers:
            return providers[0]

        logger.error("最终无法获取任何可用的AI提供商")
        return None

    async def get_market_context(self) -> str:
        """获取当前市场状况供AI参考"""
        try:
            global_data = await asyncio.to_thread(self.cg.get_global)
            data = global_data.get('data', {})
            btc_dominance = data.get('market_cap_percentage', {}).get('btc', 0)
            market_cap_change = data.get('market_cap_change_percentage_24h_usd', 0)
            sentiment = "中性"
            if market_cap_change > 2: sentiment = "贪婪"
            elif market_cap_change < -2: sentiment = "恐慌"
            return f"BTC 市值占比: {btc_dominance:.1f}%, 24小时总市值变化: {market_cap_change:.2f}%, 市场情绪: {sentiment}"
        except Exception as e:
            logger.error(f"获取市场上下文失败: {e}")
            return "市场数据暂不可用"

    def _build_strategy_prompt(self, session: dict) -> str:
        """构建初始策略的Prompt"""
        currency_list_str = ", ".join(self.target_currencies)
        return f"""
        你是一个专业的加密货币投资经理。请为初始资金为 ${session['initial_funds']:,.2f} 的投资模拟提供一个策略。

        **投资规则:**
        1. 只能投资这些币种：{currency_list_str}
        2. 最大杠杆：10倍
        3. 单币种最大仓位(现货价值+合约名义价值)不得超过总资金的30%
        4. 合约仓位总保证金不超过总资金的20%
        5. 必须保留至少10%的现金

        **请返回严格的JSON格式，不要包含任何解释性文本或代码块标记:**
        {{
          "strategy": "简要策略描述",
          "risk_level": "low/medium/high",
          "allocations": {{
            "spot": [
              {{"coin": "bitcoin", "percentage": 40}}
            ],
            "futures": [
              {{"coin": "ethereum", "percentage": 5, "leverage": 3, "side": "long"}}
            ],
            "cash": 55
          }},
          "reasoning": "选择这些仓位的理由"
        }}

        确保 `allocations` 中所有 `percentage` 的总和精确等于100%，且严格符合所有风险规则。
        """

    def _format_strategy_result(self, ai_data: dict, session: dict) -> str:
        """格式化AI策略为可读文本"""
        allocations = ai_data.get('allocations', {})
        session["suggested_allocation"] = allocations
        
        result = f"🤖 **AI投资策略分析**\n"
        result += f"**策略思路**: {ai_data.get('strategy', 'N/A')}\n"
        result += f"**风险等级**: {ai_data.get('risk_level', 'medium')}\n"
        result += f"**决策理由**: {ai_data.get('reasoning', 'N/A')}\n\n"
        result += "**建议仓位配置**:\n"
        
        spot_positions = allocations.get('spot', [])
        if spot_positions:
            result += "📍 **现货持仓**:\n"
            for pos in spot_positions:
                result += f"   • {pos.get('coin', 'N/A').capitalize()}: {pos.get('percentage', 0)}%\n"
        
        futures_positions = allocations.get('futures', [])
        if futures_positions:
            result += "📈 **合约持仓**:\n"
            for pos in futures_positions:
                side_str = "做多" if pos.get('side') == 'long' else "做空"
                result += f"   • {pos.get('coin', 'N/A').capitalize()}: {pos.get('percentage', 0)}% ({side_str} @ {pos.get('leverage', 1)}x)\n"
        
        result += f"💰 **现金储备**: {allocations.get('cash', 0)}%\n"
        return result

    async def get_ai_strategy_analysis(self, event: AstrMessageEvent, session: dict) -> str:
        """获取AI对投资策略的分析 (使用解析器)"""
        try:
            provider = await self._get_ai_provider(event=event)
            if not provider: return "无法获取AI提供商"
            
            # 关键：将获取到的provider id存入session，供后台任务使用
            # 从 provider 对象中推断出 provider_id (例如, 从 'ProviderZhipu' 得到 'zhipu')
            provider_id = provider.__class__.__name__.replace("Provider", "").lower()
            session["provider_id"] = provider_id
            
            prompt = self._build_strategy_prompt(session)
            llm_response = await provider.text_chat(
                prompt=prompt,
                system_prompt="你是一个专业的加密货币投资顾问，必须严格按照要求的JSON格式返回数据，不要使用代码块标记。"
            )
            
            ai_data = self.ai_parser.parse(llm_response.completion_text, STRATEGY_SCHEMA)
            return self._format_strategy_result(ai_data, session)
        except Exception as e:
            logger.error(f"获取AI策略分析失败: {e}", exc_info=True)
            return "获取AI策略分析时发生错误"

    async def get_ai_performance_analysis(self, event: AstrMessageEvent, session: dict, final_funds: float, profit_loss: float, profit_loss_percent: float) -> str:
        """获取AI对投资表现的分析 (使用解析器)"""
        try:
            provider = await self._get_ai_provider(event=event, session=session)
            if not provider: return "无法获取AI性能分析"

            duration_days = (time.time() - session["start_time"]) / 86400
            position_history = "持仓历史记录暂未实现。"

            prompt = f"""
            分析这次投资表现：

            **基础信息：**
            - 初始资金：${session['initial_funds']:,.2f}
            - 最终资金：${final_funds:,.2f}
            - 盈亏：${profit_loss:,.2f} ({profit_loss_percent:+.2f}%)
            - 持续时间：{duration_days:.2f}天
            **持仓历史：** {position_history}

            **请返回严格的JSON分析，不要包含任何解释性文本或代码块标记:**
            {{
              "performance_rating": 7,
              "strengths": ["优点1", "优点2"],
              "weaknesses": ["缺点1", "缺点2"],
              "key_learnings": ["学习点1", "学习点2"],
              "suggestions": ["建议1", "建议2"]
            }}
            """
            
            llm_response = await provider.text_chat(prompt=prompt, system_prompt="你是一个专业的投资分析师，必须严格按照要求的JSON格式返回数据。")
            ai_data = self.ai_parser.parse(llm_response.completion_text, PERFORMANCE_SCHEMA)
            
            result = f"**表现评分**: {ai_data.get('performance_rating', 'N/A')}/10\n"
            result += "**优点**:\n" + "".join([f"  - {s}\n" for s in ai_data.get('strengths', [])])
            result += "**待改进**:\n" + "".join([f"  - {w}\n" for w in ai_data.get('weaknesses', [])])
            result += "**核心经验**:\n" + "".join([f"  - {k}\n" for k in ai_data.get('key_learnings', [])])
            result += "**未来建议**:\n" + "".join([f"  - {s}\n" for s in ai_data.get('suggestions', [])])
            return result
        except Exception as e:
            logger.error(f"获取AI性能分析失败: {e}", exc_info=True)
            return "获取AI性能分析时发生错误"
    
    async def create_initial_positions(self, session):
        """根据AI建议创建初始混合仓位（现货 + 合约）"""
        allocations = session.get("suggested_allocation", {})
        if not allocations:
            logger.warning("AI未提供建议仓位，将全部保留为现金")
            session["cash"] = session["initial_funds"]
            return

        spot_positions = allocations.get('spot', [])
        futures_positions = allocations.get('futures', [])
        
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
                if price is None or price == 0: continue
                
                investment_amount = initial_funds * (percentage / 100)
                coin_amount = investment_amount / price
                cash_used += investment_amount
                session['spot_positions'][coin_id] = {'amount': coin_amount, 'entry_price': price, 'current_price': price, 'value': investment_amount, 'pnl': 0}
            
            # 创建合约仓位
            for pos_info in futures_positions:
                coin_id = pos_info['coin']
                percentage = pos_info.get('percentage', 0)
                leverage = pos_info.get('leverage', 1)
                side = pos_info.get('side', 'long')
                price = prices_data.get(coin_id, {}).get('usd')
                if price is None or price == 0: continue

                margin = initial_funds * (percentage / 100)
                position_value = margin * leverage
                coin_amount = position_value / price
                margin_used += margin
                liquidation_price = calculate_liquidation_price(price, leverage, side)
                session['futures_positions'][coin_id] = {'amount': coin_amount, 'entry_price': price, 'current_price': price, 'value': position_value, 'margin': margin, 'leverage': leverage, 'side': side, 'liquidation_price': liquidation_price, 'pnl': 0}

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
                await asyncio.sleep(self.rate_query_cooldown)
                if self.investment_sessions:
                    await self.update_all_sessions()
            except asyncio.CancelledError:
                logger.info("投资模拟更新任务已取消")
                break
            except Exception as e:
                logger.error(f"定期更新投资模拟失败: {e}", exc_info=True)
                await asyncio.sleep(60)

    async def update_all_sessions(self):
        """更新所有活跃的投资会话"""
        user_ids = list(self.investment_sessions.keys())
        if not user_ids: return

        all_coin_ids_set = set()
        for user_id in user_ids:
            session = self.investment_sessions.get(user_id)
            if session:
                all_coin_ids_set.update(session.get("spot_positions", {}).keys())
                all_coin_ids_set.update(session.get("futures_positions", {}).keys())
        
        if not all_coin_ids_set: return
        
        try:
            prices_data = await asyncio.to_thread(self.cg.get_price, ids=list(all_coin_ids_set), vs_currencies='usd')
            if not prices_data:
                logger.warning(f"无法为任何活跃会话获取价格数据。")
                return
        except Exception as e:
            logger.error(f"批量获取价格失败: {e}", exc_info=True)
            return

        for user_id in user_ids:
            session = self.investment_sessions.get(user_id)
            if not session: continue

            try:
                liquidated_coins = []
                # 更新合约仓位
                for coin_id, pos_data in session.get("futures_positions", {}).items():
                    current_price = prices_data.get(coin_id, {}).get('usd')
                    if current_price is None: continue # 如果没有获取到价格，则跳过此仓位更新

                    pos_data['current_price'] = current_price
                    should_liquidate, reason = check_position_risk(pos_data, current_price)
                    if should_liquidate:
                        logger.warning(f"用户 {user_id} 的 {coin_id} {pos_data['side']} 仓位已被强平！原因: {reason}")
                        session['margin_used'] -= pos_data['margin']
                        liquidated_coins.append(coin_id)
                        continue
                    pos_data['pnl'] = calculate_futures_pnl(pos_data, current_price)

                for coin_id in liquidated_coins:
                    del session['futures_positions'][coin_id]

                # 新增：检查并执行挂单（如止损）
                await self._check_pending_orders(session, prices_data)
 
                # 使用统一的函数计算总资产
                session["current_funds"] = calculate_total_assets(session, prices_data)

                if time.time() - session.get("last_ai_update_time", 0) > session.get("cooldown_period", 300):
                    asyncio.create_task(self.trigger_ai_rebalance(user_id, session))
                    session["last_ai_update_time"] = time.time()
            except Exception as e:
                logger.error(f"更新用户 {user_id} 的投资模拟会话失败: {e}", exc_info=True)
    
    @command("cry_fight_status")
    async def investment_status(self, event: AstrMessageEvent):
        """查看当前投资状态 (优化版，无网络请求)"""
        try:
            user_id = event.get_sender_id() if event.get_sender_id() else event.unified_msg_origin
            if user_id not in self.investment_sessions:
                yield event.plain_result("❌ 您没有正在进行的投资模拟")
                return
            
            session = self.investment_sessions[user_id]
            spot_positions = session.get("spot_positions", {})
            futures_positions = session.get("futures_positions", {})

            # 数据由后台任务更新，此处直接读取，无需API调用或重新计算
            current_funds = session.get("current_funds", session["initial_funds"])
            cash = session.get("cash", 0)
            margin_used = session.get("margin_used", 0)
            profit_loss = current_funds - session["initial_funds"]
            profit_loss_percent = (profit_loss / session["initial_funds"]) * 100 if session["initial_funds"] != 0 else 0
            
            result = (f"📊 **投资模拟状态**\n"
                      f"起始资金: ${session['initial_funds']:,.2f}\n"
                      f"当前总资产: ${current_funds:,.2f}\n"
                      f"总盈亏: ${profit_loss:,.2f} ({profit_loss_percent:+.2f}%)\n"
                      f"可用现金: ${cash:,.2f}\n"
                      f"--------------------\n")

            if spot_positions:
                result += "📦 **现货持仓**:\n"
                for coin_id, pos in spot_positions.items():
                    pnl = pos.get('pnl', 0)
                    entry_value = pos['amount'] * pos['entry_price']
                    pnl_percent = (pnl / entry_value) * 100 if entry_value > 0 else 0
                    result += (f"  - {coin_id.capitalize()}:\n"
                               f"    持仓价值: ${pos.get('value', 0):,.2f}\n"
                               f"    未实现盈亏: ${pnl:,.2f} ({pnl_percent:+.2f}%)\n")
            else:
                result += "📦 **现货持仓**: 无\n"

            result += "--------------------\n"

            if futures_positions:
                result += f"📈 **合约持仓** (保证金: ${margin_used:,.2f}):\n"
                for coin_id, pos in futures_positions.items():
                    side_str = "多头" if pos['side'] == 'long' else "空头"
                    pnl = pos.get('pnl', 0)
                    pnl_percent = (pnl / pos['margin']) * 100 if pos['margin'] > 0 else 0
                    result += (f"  - {coin_id.capitalize()} ({side_str} {pos.get('leverage', 1):.2f}x):\n"
                               f"    开仓价: ${pos['entry_price']:,.4f}, 当前价: ${pos.get('current_price', 0):,.4f}\n"
                               f"    强平价: ${pos['liquidation_price']:,.4f}\n"
                               f"    未实现盈亏: ${pnl:,.2f} ({pnl_percent:+.2f}%)\n")
            else:
                result += "📈 **合约持仓**: 无\n"
            
            yield event.plain_result(result)
        except Exception as e:
            logger.error(f"查看投资状态失败: {e}", exc_info=True)
            yield event.plain_result("❌ 查看投资状态失败")
    
    async def _check_pending_orders(self, session: dict, prices_data: dict):
        """检查并执行待处理订单，如止损单"""
        triggered_orders_indices = []
        user_id = session.get("user_id")

        # 使用索引进行迭代以安全地删除
        for i, order in enumerate(session.get("pending_orders", [])):
            coin_id = order.get("coin")
            if not coin_id: continue

            current_price = prices_data.get(coin_id, {}).get('usd')
            if not current_price: continue

            pos = session['futures_positions'].get(coin_id)
            if not pos:
                triggered_orders_indices.append(i)
                continue

            order_type = order.get("type")
            is_triggered = False
            trigger_price = 0
            reason_prefix = ""

            if order_type == "STOP_LOSS":
                stop_price = order["stop_price"]
                if (pos['side'] == 'long' and current_price <= stop_price) or \
                   (pos['side'] == 'short' and current_price >= stop_price):
                    is_triggered = True
                    trigger_price = stop_price
                    reason_prefix = "止损"
            
            elif order_type == "TAKE_PROFIT":
                target_price = order["target_price"]
                if (pos['side'] == 'long' and current_price >= target_price) or \
                   (pos['side'] == 'short' and current_price <= target_price):
                    is_triggered = True
                    trigger_price = target_price
                    reason_prefix = "止盈"

            if is_triggered:
                logger.info(f"用户 {user_id} 的 {coin_id} {reason_prefix}单被触发！价格: {current_price}, 目标价: {trigger_price}")
                
                close_action = {
                    "action": order["trigger_action"],
                    "coin": coin_id,
                    "reason": f"{reason_prefix}触发 at ${current_price:,.4f}"
                }
                
                summary = await self._close_futures_position(session, close_action, pos['side'])
                
                if summary and (umo := session.get("user_umo")):
                    icon = "🛡️" if order_type == "STOP_LOSS" else "🎯"
                    message = f"{icon} **{reason_prefix}执行**\n{summary}"
                    await self.context.send_message(umo, message)

                triggered_orders_indices.append(i)
        
        # 从后往前删除已触发的订单，避免索引错误
        for i in sorted(triggered_orders_indices, reverse=True):
            del session['pending_orders'][i]

    async def get_ai_rebalance_plan(self, user_id: str, session: dict) -> dict | None:
        """获取AI对当前投资组合的调仓计划 (使用新的Prompt和Schema)"""
        try:
            provider = await self._get_ai_provider(session=session)
            if not provider:
                logger.error(f"最终无法为用户 {user_id} 获取任何可用的AI提供商")
                return None

            profit_loss = session['current_funds'] - session['initial_funds']
            profit_loss_percent = (profit_loss / session['initial_funds']) * 100 if session['initial_funds'] > 0 else 0

            portfolio_summary = {
                "total_funds": session['current_funds'], "initial_funds": session['initial_funds'],
                "profit_loss_percent": profit_loss_percent, "cash": session['cash'],
                "spot_positions": {c: {"value": p.get('value',0), "pnl": p.get('pnl',0), "current_price": p.get('current_price')} for c,p in session.get("spot_positions",{}).items()},
                "futures_positions": {c: {"side": p.get('side'), "leverage": p.get('leverage'), "pnl": p.get('pnl',0), "current_price": p.get('current_price')} for c,p in session.get("futures_positions",{}).items()}
            }
            market_context = await self.get_market_context()
            currency_list_str = ", ".join(self.target_currencies)

            prompt = f"""
            你是一个顶级的加密货币基金经理，负责管理一个动态的投资组合。

            **当前投资组合状态:**
            {json.dumps(portfolio_summary, indent=2, ensure_ascii=False)}

            **你的任务:** 根据当前市场状况和投资组合表现，决定最佳操作。

            **可用操作类型 (选择一种或多种):**

            ## 🎯 核心交易操作:
            - `BUY_SPOT`: 买入现货 `{{"action": "BUY_SPOT", "coin": "bitcoin", "percentage_of_cash": 15, "reason": "价值投资"}}`
            - `SELL_SPOT`: 卖出现货 `{{"action": "SELL_SPOT", "coin": "ethereum", "percentage_of_holding": 50, "reason": "获利了结"}}`

            ## 📈 合约方向操作:
            - `OPEN_LONG`: 开多头 `{{"action": "OPEN_LONG", "coin": "solana", "percentage_of_cash": 8, "leverage": 5, "reason": "技术突破"}}`
            - `OPEN_SHORT`: 开空头 `{{"action": "OPEN_SHORT", "coin": "bitcoin", "percentage_of_cash": 6, "leverage": 8, "reason": "阻力位受阻"}}`
            - `CLOSE_LONG`: 平多头 `{{"action": "CLOSE_LONG", "coin": "ethereum", "reason": "达到目标位"}}`
            - `CLOSE_SHORT`: 平空头 `{{"action": "CLOSE_SHORT", "coin": "solana", "reason": "支撑位反弹"}}`

            ## ⚖️ 仓位管理操作:
            - `ADD_MARGIN`: 增加保证金 `{{"action": "ADD_MARGIN", "coin": "bitcoin", "percentage_of_cash": 3, "reason": "降低强平风险"}}`
            - `REDUCE_MARGIN`: 减少保证金 `{{"action": "REDUCE_MARGIN", "coin": "ethereum", "percentage_of_margin": 30, "reason": "提取浮动盈利"}}`
            - `INCREASE_LEVERAGE`: 提高杠杆 `{{"action": "INCREASE_LEVERAGE", "coin": "solana", "new_leverage": 10, "reason": "趋势确认"}}`
            - `DECREASE_LEVERAGE`: 降低杠杆 `{{"action": "DECREASE_LEVERAGE", "coin": "bitcoin", "new_leverage": 3, "reason": "风险控制"}}`

            ## 🛡️ 风险管理操作:
            - `SET_STOP_LOSS`: 设置止损 `{{"action": "SET_STOP_LOSS", "coin": "ethereum", "stop_price": 2500, "reason": "控制下行风险"}}`
            - `SET_TAKE_PROFIT`: 设置止盈 `{{"action": "SET_TAKE_PROFIT", "coin": "ethereum", "target_price": 3500, "reason": "达到目标盈利位"}}`

            ## 🎮 策略操作:
            - `HOLD`: 保持现状 `{{"action": "HOLD", "reason": "市场趋势未变，当前仓位最优"}}`

            **投资规则:**
            - 可选币种: {currency_list_str}
            - 单次开仓保证金 ≤ 15%
            - 合约杠杆范围: 1-100倍
            - 总合约保证金 ≤ 总资金25%
            - 必须保留 ≥ 10% 现金
            - 同币种不能同时持有多头和空头仓位

            **市场分析参考:**
            {market_context}

            **请返回严格的JSON格式:**
            {{
              "analysis": "详细的市场分析和多空判断理由",
              "market_direction": "bullish/bearish/neutral",
              "confidence_level": "high/medium/low",
              "time_horizon": "short_term/medium_term/long_term",
              "actions": [ ]
            }}
            如果决定不操作，"actions"数组中应只包含一个HOLD操作。
            """
            umo = session.get("user_umo")
            history = []
            if umo:
                try:
                    conv_mgr = self.context.conversation_manager
                    curr_cid = await conv_mgr.get_curr_conversation_id(umo)
                    if curr_cid:
                        conversation = await conv_mgr.get_conversation(umo, curr_cid)
                        if conversation and conversation.history:
                            history = json.loads(conversation.history)
                except Exception as e:
                    logger.warning(f"为 {umo} 获取对话历史失败: {e}")

            llm_response = await provider.text_chat(
                prompt=prompt,
                system_prompt="你是一个专业的加密货币基金经理，必须严格按照要求的JSON格式返回决策。",
                context=history
            )
            return self.ai_parser.parse(llm_response.completion_text, REBALANCE_SCHEMA)
        except Exception as e:
            logger.error(f"获取AI调仓计划失败: {e}", exc_info=True)
            return None

    async def trigger_ai_rebalance(self, user_id: str, session: dict):
        """触发AI进行调仓决策并执行"""
        plan = await self.get_ai_rebalance_plan(user_id, session)
        if not plan or not plan.get("actions") or (len(plan["actions"]) == 1 and plan["actions"][0].get("action") == "HOLD"):
            reason = plan['actions'][0].get('reason') if plan and plan.get('actions') else '无有效计划'
            logger.info(f"用户 {user_id} 的AI决定保持仓位不变。理由: {reason}")
            return
            
        execution_summary = await self.execute_rebalance_plan(session, plan)
        analysis = plan.get("analysis", "无分析。")
        if execution_summary:
            message = f"🤖 **AI 投资组合调整已执行**\n\n**分析:** {analysis}\n\n**执行操作:**\n" + "\n".join(execution_summary)
            if umo := session.get("user_umo"):
                await self.context.send_message(umo, message)

    async def _validate_action(self, session: dict, action: dict, temp_session_state: dict) -> OperationResult:
        """对单个操作进行全面的参数和前提条件验证"""
        
        # 1. 参数完整性验证
        param_errors = self._validate_action_parameters(action)
        if param_errors:
            return OperationResult(False, f"参数错误: {', '.join(param_errors)}")

        # 2. 投资组合级别的风险验证
        risk_error = self._validate_portfolio_risk(action, temp_session_state)
        if risk_error:
            return OperationResult(False, risk_error)

        return OperationResult(True, "验证通过")

    def _validate_action_parameters(self, action: dict) -> list[str]:
        """验证操作参数的完整性、类型和范围"""
        errors = []
        action_type = action.get("action")
        
        # 检查必需参数
        required_params = self.ACTION_REQUIREMENTS.get(action_type, [])
        for param in required_params:
            if param not in action:
                errors.append(f"缺少必需参数: {param}")
        if errors: return errors # 如果缺少参数，提前返回

        # 检查通用数值参数的类型和范围
        for param_name in ["percentage_of_cash", "percentage_of_holding", "percentage_of_margin"]:
            if param_name in action:
                val = action[param_name]
                if not isinstance(val, (int, float)) or not (0 <= val <= 100):
                    errors.append(f"参数 '{param_name}' 的值 ({val}) 必须是0-100之间的数字")

        if "leverage" in action and not (isinstance(action["leverage"], (int, float)) and 1 <= action["leverage"] <= 100):
            errors.append(f"杠杆倍数必须是1-100之间的数字")
        
        return errors

    def _validate_portfolio_risk(self, action: dict, temp_session_state: dict) -> str | None:
        """验证操作是否会违反投资组合级别的风险规则"""
        action_type = action.get("action")
        
        # 规则1: 总保证金使用率不得超过 25%
        if action_type in ("OPEN_LONG", "OPEN_SHORT"):
            margin_to_use = temp_session_state['cash'] * (action.get('percentage_of_cash', 0) / 100)
            simulated_margin_used = temp_session_state.get("margin_used", 0) + margin_to_use
            simulated_funds = temp_session_state.get("current_funds", 1)
            
            if simulated_funds > 0 and (simulated_margin_used / simulated_funds) > 0.25:
                return f"风险过高: 开仓将导致总保证金使用率超过25%"

        # 规则2: 必须保留至少 10% 的现金
        if action_type in ("OPEN_LONG", "OPEN_SHORT", "BUY_SPOT", "ADD_MARGIN"):
            cash_to_use = temp_session_state['cash'] * (action.get('percentage_of_cash', 0) / 100)
            simulated_cash = temp_session_state.get("cash", 0) - cash_to_use
            simulated_funds = temp_session_state.get("current_funds", 1)
            
            if simulated_funds > 0 and (simulated_cash / simulated_funds) < 0.10:
                return f"现金不足: 操作将导致现金储备低于10%"

        return None # 验证通过

    async def execute_rebalance_plan(self, session: dict, plan: dict) -> list[str]:
        """以事务性方式执行AI返回的调仓计划，并进行严格验证"""
        actions = plan.get("actions", [])
        summary = []
        
        session_backup = copy.deepcopy(session)
        temp_session_state = copy.deepcopy(session)

        try:
            for action in actions:
                action_type = action.get("action", "Unknown")
                coin = action.get("coin", "N/A")
                
                # 1. 综合验证
                validation_result = await self._validate_action(session, action, temp_session_state)
                if not validation_result.success:
                    raise ValueError(f"操作 '{action_type}'({coin}) 验证失败: {validation_result.message}")

                # 2. 查找并执行处理器
                # HOLD是一个特殊的无操作指令，直接跳过
                if action_type == "HOLD":
                    summary.append("✅ AI决定保持仓位不变")
                    continue

                handler = getattr(self, f"_handle_{action_type.lower()}", None)
                if not handler:
                    raise ValueError(f"未知的操作类型: {action_type}")
                
                # 3. 执行操作并处理结果
                op_result: OperationResult = await handler(session, action)
                if op_result.success:
                    summary.append(op_result.message)
                    # 操作成功后，同步更新临时状态以供下一步验证
                    temp_session_state = copy.deepcopy(session)
                else:
                    # 如果单个处理器执行失败，则抛出异常以触发回滚
                    raise ValueError(f"操作 '{action_type}'({coin}) 执行失败: {op_result.message}")
            
            return summary
            
        except Exception as e:
            user_id = session.get("user_id")
            logger.error(f"执行用户 {user_id} 的调仓计划失败，将回滚所有操作。错误: {e}", exc_info=True)
            if user_id and user_id in self.investment_sessions:
                self.investment_sessions[user_id] = session_backup
            
            return [f"❌ **操作失败并已回滚**", f"   原因: {e}"]

    async def _get_current_price(self, coin_id: str) -> float | None:
        """获取单个币种的当前价格"""
        try:
            price_data = await asyncio.to_thread(self.cg.get_price, ids=coin_id, vs_currencies='usd')
            return price_data.get(coin_id, {}).get('usd')
        except Exception as e:
            logger.error(f"获取 {coin_id} 价格失败: {e}")
            return None

    # --- Action Handlers ---

    async def _handle_buy_spot(self, session: dict, action: dict) -> OperationResult:
        coin_id = action["coin"]
        price = await self._get_current_price(coin_id)
        if not price: return OperationResult(False, f"无法获取 {coin_id} 的价格")
        
        amount_to_invest = session['cash'] * (action['percentage_of_cash'] / 100)
        if amount_to_invest <= 0: return OperationResult(True, "投资金额为0，无操作")
        if session['cash'] < amount_to_invest:
            return OperationResult(False, f"现金不足 (需要 ${amount_to_invest:,.2f}, 可用 ${session['cash']:.2f})")

        coin_amount = amount_to_invest / price
        session['cash'] -= amount_to_invest
        
        if coin_id not in session['spot_positions']:
            session['spot_positions'][coin_id] = {'amount': 0, 'entry_price': price}
        pos = session['spot_positions'][coin_id]
        new_total_cost = (pos['amount'] * pos['entry_price']) + amount_to_invest
        pos['amount'] += coin_amount
        pos['entry_price'] = new_total_cost / pos['amount']
        return OperationResult(True, f"✅ 使用 ${amount_to_invest:,.2f} 买入 {coin_id.upper()} 现货")

    async def _handle_sell_spot(self, session: dict, action: dict) -> OperationResult:
        coin_id = action["coin"]
        pos = session['spot_positions'].get(coin_id)
        if not pos: return OperationResult(False, f"未持有 {coin_id} 现货")
        
        price = await self._get_current_price(coin_id) or pos.get('current_price', pos['entry_price'])
        
        percentage = action['percentage_of_holding']
        amount_to_sell = pos['amount'] * (percentage / 100)
        if amount_to_sell <= 0: return OperationResult(True, "卖出数量为0，无操作")
        
        cash_gained = amount_to_sell * price
        session['cash'] += cash_gained
        pos['amount'] -= amount_to_sell
        
        if pos['amount'] < 1e-9: del session['spot_positions'][coin_id]
        return OperationResult(True, f"✅ 卖出 {percentage}% 的 {coin_id.upper()} 现货，获得 ${cash_gained:,.2f}")

    async def _handle_open_long(self, session: dict, action: dict) -> OperationResult:
        return await self._open_futures_position(session, action, "long")

    async def _handle_open_short(self, session: dict, action: dict) -> OperationResult:
        return await self._open_futures_position(session, action, "short")

    async def _open_futures_position(self, session: dict, action: dict, side: str) -> OperationResult:
        coin_id = action["coin"]
        if (existing_pos := session['futures_positions'].get(coin_id)) and existing_pos['side'] != side:
            return OperationResult(False, f"已存在 {coin_id} 的反向仓位")
        
        price = await self._get_current_price(coin_id)
        if not price: return OperationResult(False, f"无法获取 {coin_id} 的价格")

        margin_to_use = session['cash'] * (action['percentage_of_cash'] / 100)
        if margin_to_use <= 0: return OperationResult(True, "保证金为0，无操作")
        if session['cash'] < margin_to_use:
            return OperationResult(False, f"现金不足 (需要 ${margin_to_use:,.2f}, 可用 ${session['cash']:.2f})")
        
        leverage = action['leverage']
        session['cash'] -= margin_to_use
        session['margin_used'] += margin_to_use
        
        position_value_to_add = margin_to_use * leverage
        coin_amount_to_add = position_value_to_add / price
        side_str = "多单" if side == "long" else "空单"

        if existing_pos:
            new_total_value = existing_pos['value'] + position_value_to_add
            new_total_margin = existing_pos['margin'] + margin_to_use
            new_total_amount = existing_pos['amount'] + coin_amount_to_add
            existing_pos.update({
                'entry_price': new_total_value / new_total_amount if new_total_amount > 0 else 0,
                'margin': new_total_margin, 'amount': new_total_amount, 'value': new_total_value,
                'leverage': new_total_value / new_total_margin if new_total_margin > 0 else 0
            })
            existing_pos['liquidation_price'] = calculate_liquidation_price(existing_pos['entry_price'], existing_pos['leverage'], side)
            return OperationResult(True, f"✅ 为 {coin_id.upper()} {side_str} 加仓 ${margin_to_use:,.2f} 保证金")
        else:
            liq_price = calculate_liquidation_price(price, leverage, side)
            session['futures_positions'][coin_id] = {
                'amount': coin_amount_to_add, 'entry_price': price, 'current_price': price,
                'value': position_value_to_add, 'margin': margin_to_use, 'leverage': leverage,
                'side': side, 'liquidation_price': liq_price, 'pnl': 0
            }
            return OperationResult(True, f"✅ 使用 ${margin_to_use:,.2f} 保证金开立 {coin_id.upper()} {leverage}x {side_str}")

    async def _handle_close_long(self, session: dict, action: dict) -> OperationResult:
        return await self._close_futures_position(session, action, "long")

    async def _handle_close_short(self, session: dict, action: dict) -> OperationResult:
        return await self._close_futures_position(session, action, "short")

    async def _close_futures_position(self, session: dict, action: dict, side: str) -> OperationResult:
        coin_id = action["coin"]
        pos = session['futures_positions'].get(coin_id)
        if not pos or pos['side'] != side: return OperationResult(False, f"无此 {coin_id} {side} 仓位")
        
        price = await self._get_current_price(coin_id) or pos['current_price']
        pnl = calculate_futures_pnl(pos, price)
        cash_returned = pos['margin'] + pnl
        session['cash'] += cash_returned
        session['margin_used'] -= pos['margin']
        del session['futures_positions'][coin_id]
        return OperationResult(True, f"✅ 平仓 {coin_id.upper()} {side} 合约，盈亏 ${pnl:,.2f}，总返还 ${cash_returned:,.2f}")

    async def _handle_add_margin(self, session: dict, action: dict) -> OperationResult:
        coin_id = action["coin"]
        pos = session['futures_positions'].get(coin_id)
        if not pos: return OperationResult(False, f"未找到 {coin_id} 仓位")

        amount_to_add = session['cash'] * (action['percentage_of_cash'] / 100)
        if amount_to_add <= 0: return OperationResult(True, "增加保证金为0，无操作")
        if session['cash'] < amount_to_add: return OperationResult(False, "现金不足")

        session['cash'] -= amount_to_add
        session['margin_used'] += amount_to_add
        pos['margin'] += amount_to_add
        pos['leverage'] = pos['value'] / pos['margin'] if pos['margin'] > 0 else 0
        pos['liquidation_price'] = calculate_liquidation_price(pos['entry_price'], pos['leverage'], pos['side'])
        return OperationResult(True, f"✅ 为 {coin_id.upper()} 仓位增加 ${amount_to_add:,.2f} 保证金, 新杠杆为 {pos['leverage']:.2f}x")

    async def _handle_reduce_margin(self, session: dict, action: dict) -> OperationResult:
        coin_id = action["coin"]
        pos = session['futures_positions'].get(coin_id)
        if not pos: return OperationResult(False, f"未找到 {coin_id} 仓位")

        price = await self._get_current_price(coin_id) or pos['current_price']
        pnl = calculate_futures_pnl(pos, price)
        if pnl <= 0: return OperationResult(False, f"{coin_id} 仓位没有浮动盈利")

        amount_to_reduce = pos['margin'] * (action['percentage_of_margin'] / 100)
        if amount_to_reduce <= 0: return OperationResult(True, "减少保证金为0，无操作")
        
        if amount_to_reduce > pnl:
            return OperationResult(False, f"提取金额 (${amount_to_reduce:,.2f}) 超过当前浮动盈利 (${pnl:,.2f})")

        new_margin = pos['margin'] - amount_to_reduce
        min_required_margin = calculate_minimum_margin(pos['amount'] * price)
        
        if new_margin < min_required_margin:
            return OperationResult(False, f"操作将导致保证金低于维持水平 (需要 {min_required_margin:,.2f})")

        session['cash'] += amount_to_reduce
        session['margin_used'] -= amount_to_reduce
        pos['margin'] = new_margin
        pos['leverage'] = pos['value'] / pos['margin'] if pos['margin'] > 0 else float('inf')
        pos['liquidation_price'] = calculate_liquidation_price(pos['entry_price'], pos['leverage'], pos['side'])
        return OperationResult(True, f"✅ 从 {coin_id.upper()} 仓位提取 ${amount_to_reduce:,.2f} 保证金, 新杠杆为 {pos['leverage']:.2f}x")

    async def _handle_increase_leverage(self, session: dict, action: dict) -> OperationResult:
        coin_id = action["coin"]
        pos = session['futures_positions'].get(coin_id)
        if not pos: return OperationResult(False, f"未找到 {coin_id} 仓位")

        new_leverage = action['new_leverage']
        if new_leverage <= pos['leverage']:
            return OperationResult(False, f"新杠杆 ({new_leverage}x) 必须高于当前杠杆 ({pos['leverage']:.2f}x)")
        if new_leverage > 100:
            return OperationResult(False, f"新杠杆 ({new_leverage}x) 超过最大限制 (100x)")

        price = await self._get_current_price(coin_id) or pos['current_price']
        new_margin = (pos['amount'] * price) / new_leverage
        margin_released = pos['margin'] - new_margin
        
        new_liquidation_price = calculate_liquidation_price(pos['entry_price'], new_leverage, pos['side'])
        if (pos['side'] == 'long' and price <= new_liquidation_price) or \
           (pos['side'] == 'short' and price >= new_liquidation_price):
            return OperationResult(False, f"新杠杆将导致立即强平 (强平价: ${new_liquidation_price:,.4f})")

        session['cash'] += margin_released
        session['margin_used'] -= margin_released
        pos.update({'margin': new_margin, 'leverage': new_leverage, 'liquidation_price': new_liquidation_price})
        return OperationResult(True, f"✅ {coin_id.upper()} 仓位杠杆提高至 {new_leverage:.2f}x, 释放保证金 ${margin_released:,.2f}")
        
    async def _handle_decrease_leverage(self, session: dict, action: dict) -> OperationResult:
        coin_id = action["coin"]
        pos = session['futures_positions'].get(coin_id)
        if not pos: return OperationResult(False, f"未找到 {coin_id} 仓位")

        new_leverage = action['new_leverage']
        if new_leverage >= pos['leverage']:
            return OperationResult(False, f"新杠杆 ({new_leverage}x) 必须低于当前杠杆 ({pos['leverage']:.2f}x)")
        if new_leverage < 1: return OperationResult(False, "杠杆不能低于1x")

        price = await self._get_current_price(coin_id) or pos['current_price']
        new_margin = (pos['amount'] * price) / new_leverage
        margin_to_add = new_margin - pos['margin']

        if session['cash'] < margin_to_add:
            return OperationResult(False, f"现金不足 (需要 ${margin_to_add:,.2f}, 可用 ${session['cash']:.2f})")

        session['cash'] -= margin_to_add
        session['margin_used'] += margin_to_add
        pos.update({'margin': new_margin, 'leverage': new_leverage})
        pos['liquidation_price'] = calculate_liquidation_price(pos['entry_price'], new_leverage, pos['side'])
        return OperationResult(True, f"✅ {coin_id.upper()} 仓位杠杆降低至 {new_leverage:.2f}x, 追加保证金 ${margin_to_add:,.2f}")

    async def _handle_set_stop_loss(self, session: dict, action: dict) -> OperationResult:
        return await self._create_conditional_order(session, action, "STOP_LOSS")

    async def _handle_set_take_profit(self, session: dict, action: dict) -> OperationResult:
        return await self._create_conditional_order(session, action, "TAKE_PROFIT")

    async def _create_conditional_order(self, session: dict, action: dict, order_type: str) -> OperationResult:
        """通用函数，用于创建止损或止盈订单"""
        coin_id = action.get("coin")
        price_key = "stop_price" if order_type == "STOP_LOSS" else "target_price"
        price_val = action.get(price_key)
        pos = session['futures_positions'].get(coin_id)
        if not pos: return OperationResult(False, f"未找到 {coin_id} 的合约仓位")

        current_price = pos.get('current_price', pos.get('entry_price'))
        
        # 验证价格的有效性
        error_msg = ""
        if order_type == "STOP_LOSS":
            if pos['side'] == 'long' and price_val >= current_price: error_msg = f"多头止损价格 (${price_val:,.2f}) 必须低于当前价 (${current_price:,.2f})"
            if pos['side'] == 'short' and price_val <= current_price: error_msg = f"空头止损价格 (${price_val:,.2f}) 必须高于当前价 (${current_price:,.2f})"
        elif order_type == "TAKE_PROFIT":
            if pos['side'] == 'long' and price_val <= current_price: error_msg = f"多头止盈价格 (${price_val:,.2f}) 必须高于当前价 (${current_price:,.2f})"
            if pos['side'] == 'short' and price_val >= current_price: error_msg = f"空头止盈价格 (${price_val:,.2f}) 必须低于当前价 (${current_price:,.2f})"
        if error_msg: return OperationResult(False, error_msg)

        trigger_action = "CLOSE_LONG" if pos['side'] == 'long' else "CLOSE_SHORT"
        
        session['pending_orders'] = [o for o in session.get('pending_orders', []) if not (o.get('coin') == coin_id and o.get('type') == order_type)]

        order = {
            "type": order_type, "coin": coin_id, price_key: float(price_val),
            "trigger_action": trigger_action, "reason": action.get("reason", f"AI设置{order_type}")
        }
        session['pending_orders'].append(order)
        
        order_type_str = "止损" if order_type == "STOP_LOSS" else "止盈"
        return OperationResult(True, f"✅ 为 {coin_id.upper()} {pos['side']} 仓位设置{order_type_str}于 ${float(price_val):,.4f}")

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        self._save_sessions_to_file()
        if hasattr(self, 'update_task') and self.update_task:
            self.update_task.cancel()
        if hasattr(self, 'save_task') and self.save_task:
            self.save_task.cancel()

    def _save_sessions_to_file(self):
        """将所有投资会话保存到JSON文件"""
        try:
            with open(self.sessions_file, 'w', encoding='utf-8') as f:
                json.dump(self.investment_sessions, f, ensure_ascii=False, indent=4)
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
                self._save_sessions_to_file()
