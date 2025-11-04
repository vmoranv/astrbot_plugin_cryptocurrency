# -*- coding: utf-8 -*-

def calculate_futures_pnl(position: dict, current_price: float) -> float:
    """
    计算单个合约仓位的未实现盈亏 (PnL).
    根据用户的建议，这里的计算包含了杠杆。

    :param position: 包含仓位信息的字典。
    :param current_price: 当前币种价格。
    :return: 未实现盈亏。
    """
    price_diff = current_price - position['entry_price']
    if position['side'] == 'short':
        price_diff = -price_diff
    
    # 根据用户反馈，盈亏计算需要乘以杠杆倍数
    # PnL = (价格变动) * (数量) * (杠杆)
    pnl = price_diff * position['amount'] * position['leverage']
    return pnl

def calculate_liquidation_price(entry_price: float, leverage: int, side: str, maintenance_margin_rate: float = 0.05) -> float:
    """
    计算考虑了维持保证金的强平价格。

    :param entry_price: 开仓价格。
    :param leverage: 杠杆倍数。
    :param side: 'long' 或 'short'。
    :param maintenance_margin_rate: 维持保证金率 (例如 5% = 0.05)。
    :return: 强平价格。
    """
    if leverage == 0:
        return float('inf') if side == 'long' else 0

    if side == 'long':
        # 多头强平价 = 开仓价 * (1 - (1 - 维持保证金率) / 杠杆)
        return entry_price * (1 - (1 - maintenance_margin_rate) / leverage)
    else:  # short
        # 空头强平价 = 开仓价 * (1 + (1 - 维持保证金率) / 杠杆)
        return entry_price * (1 + (1 - maintenance_margin_rate) / leverage)

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

def check_position_risk(position: dict, current_price: float) -> tuple[bool, str]:
    """
    检查单个仓位的风险，确定是否需要强平。
    规则：当仓位净值低于初始保证金的20%时，触发强平。

    :param position: 仓位信息。
    :param current_price: 当前价格。
    :return: (是否需要强平, 原因)
    """
    # 检查价格触发的强平
    if position['side'] == 'long' and current_price <= position['liquidation_price']:
        return True, f"价格 ({current_price:.4f}) 触及或低于强平价格 ({position['liquidation_price']:.4f})"
    if position['side'] == 'short' and current_price >= position['liquidation_price']:
        return True, f"价格 ({current_price:.4f}) 触及或高于强平价格 ({position['liquidation_price']:.4f})"

    # 检查基于保证金的风险
    pnl = calculate_futures_pnl(position, current_price)
    position_equity = position['margin'] + pnl
    
    # 如果仓位净值低于初始保证金的20%，则标记为高风险并建议强平
    if position_equity < position['margin'] * 0.2:
        return True, f"仓位净值 ({position_equity:.2f}) 过低，低于初始保证金的20%"
        
    return False, "风险可控"