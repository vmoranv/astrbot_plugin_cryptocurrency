from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import asyncio

from pycoingecko import CoinGeckoAPI

@register("cryptocurrency", "vmoranv", "加密货币价格查询插件", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.cg = CoinGeckoAPI()

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""

    def search_coin_sync(self, query: str) -> str:
        """使用 CoinGecko 搜索功能查找币种 ID"""
        try:
            # 使用 CoinGecko 的搜索 API
            results = self.cg.search(query=query)
            
            # 搜索结果格式: {'coins': [{'id': 'bitcoin', 'name': 'Bitcoin', 'symbol': 'BTC', ...}, ...], ...}
            if results and 'coins' in results and len(results['coins']) > 0:
                # 返回第一个匹配结果的 ID
                return results['coins'][0]['id']
            return None
        except Exception as e:
            logger.error(f"搜索币种失败: {e}", exc_info=True)
            return None
    
    def get_price_sync(self, coin_id: str) -> dict:
        """同步方法：查询加密货币价格（在线程池中执行）"""
        try:
            price_data = self.cg.get_price(ids=coin_id, vs_currencies='usd')
            return price_data
        except Exception as e:
            logger.error(f"查询价格失败: {e}", exc_info=True)
            raise

    @filter.command("get_crypto_price", alias={'crypto'})
    async def query_crypto_price(self, event: AstrMessageEvent, symbol: str):
        """查询加密货币对 USD 的实时汇率，使用格式：/crypto 币种代号"""
        try:
            if not symbol:
                yield event.plain_result("❌ 格式错误，请使用：/crypto 币种代号\n例如：/crypto btc 或 /crypto bitcoin")
                return

            # 首先尝试直接使用输入作为 coin_id（可能已经是正确的 ID）
            coin_id = symbol.lower().strip()
            
            # 在线程池中执行同步的 API 调用
            # 步骤1：尝试直接查询（如果输入已经是正确的 coin_id）
            try:
                price_data = await asyncio.wait_for(
                    asyncio.to_thread(self.get_price_sync, coin_id),
                    timeout=10.0
                )
                
                # 如果直接查询成功，使用结果
                if price_data and coin_id in price_data and 'usd' in price_data[coin_id]:
                    price = price_data[coin_id]['usd']
                else:
                    # 如果直接查询失败，使用搜索功能查找币种 ID
                    coin_id = await asyncio.wait_for(
                        asyncio.to_thread(self.search_coin_sync, symbol),
                        timeout=10.0
                    )
                    
                    if not coin_id:
                        yield event.plain_result(f"❌ 未找到币种 '{symbol}'，请检查币种代号是否正确")
                        return
                    
                    # 使用搜索到的 coin_id 查询价格
                    price_data = await asyncio.wait_for(
                        asyncio.to_thread(self.get_price_sync, coin_id),
                        timeout=10.0
                    )
                    
                    if not price_data or coin_id not in price_data or 'usd' not in price_data[coin_id]:
                        yield event.plain_result(f"❌ 未找到币种 '{symbol}' 的价格信息")
                        return
                    
                    price = price_data[coin_id]['usd']
                    
            except asyncio.TimeoutError:
                logger.error(f"查询 {symbol} 超时")
                yield event.plain_result("❌ 查询超时，请稍后重试")
                return
            except Exception as e:
                logger.error(f"API 调用失败: {e}", exc_info=True)
                yield event.plain_result(f"❌ 查询失败：{str(e)}\n请检查网络连接或稍后重试")
                return
            
            # 格式化价格显示
            if price >= 1:
                price_str = f"${price:,.2f}"
            else:
                # 对于小于1的价格，显示更多小数位
                price_str = f"${price:.6f}".rstrip('0').rstrip('.')
            
            result = f"💰 {symbol.upper()} / USD\n当前价格: {price_str} USD"
            yield event.plain_result(result)
            
        except Exception as e:
            logger.error(f"查询加密货币价格失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 查询失败：{str(e)}\n请稍后重试或检查网络连接")

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
