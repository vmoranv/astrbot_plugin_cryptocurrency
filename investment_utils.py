# -*- coding: utf-8 -*-
from astrbot.api import logger

def calculate_futures_pnl(position: dict, current_price: float) -> float:
    """
    计算单个合约仓位的未实现盈亏 (PnL).
    重要：这里的 position['amount'] 是指合约代表的币的数量（名义价值 / 开仓价），
    因此计算 PnL 时不应再乘以杠杆。

    :param position: 包含仓位信息的字典。
    :param current_price: 当前币种价格。
    :return: 未实现盈亏。
    """
    price_diff = current_price - position['entry_price']
    if position['side'] == 'short':
        price_diff = -price_diff
    
    # 正确的 PnL 计算: PnL = (价格变动) * (币的数量)
    pnl = price_diff * position['amount']
    return pnl

def get_maintenance_margin_rate(position_value: float, coin_id: str) -> float:
    """
    模拟阶梯保证金制度
    仓位越大，维持保证金率越高
    """
    if position_value <= 50000:
        return 0.005  # 0.5%
    elif position_value <= 200000:
        return 0.008  # 0.8%
    else:
        return 0.012  # 1.2%

def calculate_liquidation_price(entry_price: float, leverage: int, side: str,
                              maintenance_margin_rate: float = 0.005,
                              liquidation_fee_rate: float = 0.0005) -> float:
    """
    更精确的强平价格计算，考虑维持保证金率和强平手续费
    """
    if leverage == 0:
        return float('inf') if side == 'long' else 0

    if side == 'long':
        # 多头：考虑强平手续费的影响
        return entry_price * (1 - (1 - maintenance_margin_rate - liquidation_fee_rate) / leverage)
    else:
        # 空头：考虑强平手续费的影响
        return entry_price * (1 + (1 - maintenance_margin_rate - liquidation_fee_rate) / leverage)

def calculate_total_assets(session: dict, prices_data: dict) -> float:
    """
    计算账户总资产净值 (Total Equity)。
    总资产 = 现金 + 现货总价值 + 合约账户权益

    :param session: 用户会话对象。
    :param prices_data: 最新的价格数据。
    :return: 账户总资产净值。
    """
    cash = session.get("cash", 0)
    
    # 1. 计算现货总价值
    spot_value = 0
    for coin_id, pos in session.get("spot_positions", {}).items():
        current_price = prices_data.get(coin_id, {}).get('usd', pos.get('current_price', pos['entry_price']))
        spot_value += pos['amount'] * current_price
    
    # 2. 计算合约账户权益 (Futures Equity)
    # 合约权益 = 已用保证金 + 所有合约的总盈亏
    margin_used = session.get("margin_used", 0)
    total_futures_pnl = 0
    for coin_id, pos in session.get("futures_positions", {}).items():
        current_price = prices_data.get(coin_id, {}).get('usd', pos.get('current_price', pos['entry_price']))
        total_futures_pnl += calculate_futures_pnl(pos, current_price)
    
    futures_equity = margin_used + total_futures_pnl
    
    # 3. 计算总资产
    total_assets = cash + spot_value + futures_equity
    return total_assets

def calculate_maintenance_margin(position: dict, current_price: float) -> float:
    """计算维持保证金要求"""
    position_value = position['amount'] * current_price
    maintenance_margin_rate = get_maintenance_margin_rate(position_value, position.get('coin', ''))
    return position_value * maintenance_margin_rate

def calculate_margin_ratio(position: dict, current_price: float) -> float:
    """正确的保证金率计算"""
    maintenance_margin_required = calculate_maintenance_margin(position, current_price)
    
    if maintenance_margin_required <= 0:
        return float('inf')
    
    # 使用保证金余额（不含未实现盈亏）
    return position['margin'] / maintenance_margin_required

def check_position_risk(position: dict, current_price: float) -> tuple[bool, str]:
    """修复后的强平检测"""
    # 使用标记价格进行风险检查
    mark_price = current_price  # 实际应该使用 get_mark_price()
    
    margin_ratio = calculate_margin_ratio(position, mark_price)
    
    
    # 强平条件：保证金率 <= 100%
    if margin_ratio <= 1.0:
        return True, f"保证金率 ({margin_ratio:.2%}) 达到强平阈值"
    
    # 价格强平检查
    if position['side'] == 'long' and mark_price <= position['liquidation_price']:
        return True, f"标记价格触及强平线"
    if position['side'] == 'short' and mark_price >= position['liquidation_price']:
        return True, f"标记价格触及强平线"
        
    return False, "风险可控"

def calculate_total_margin_usage_ratio(session: dict) -> float:
    """计算总保证金使用率"""
    margin_used = session.get("margin_used", 0)
    current_funds = session.get("current_funds", 1)
    if current_funds == 0: return 0
    return margin_used / current_funds

def calculate_coin_exposure(session: dict, coin_id: str, current_price: float) -> float:
    """计算单个币种的风险暴露度"""
    spot_value = 0
    if (spot_pos := session.get("spot_positions", {}).get(coin_id)):
        spot_value = spot_pos['amount'] * current_price

    futures_value = 0
    if (futures_pos := session.get("futures_positions", {}).get(coin_id)):
        futures_value = futures_pos['amount'] * current_price

    total_exposure = spot_value + futures_value
    current_funds = session.get("current_funds", 1)
    if current_funds == 0: return 0
    
    return total_exposure / current_funds