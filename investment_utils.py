# -*- coding: utf-8 -*-

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

def calculate_margin_ratio(position: dict, current_price: float) -> float:
    """计算当前保证金率"""
    pnl = calculate_futures_pnl(position, current_price)
    position_equity = position['margin'] + pnl
    position_value = position['amount'] * current_price
    
    if position_value == 0:
        return float('inf')
        
    return position_equity / position_value

def check_position_risk(position: dict, current_price: float) -> tuple[bool, str]:
    """
    对单个仓位进行多维度风险检查。

    :param position: 仓位信息。
    :param current_price: 当前价格。
    :return: (是否需要强平, 原因)
    """
    # 1. 价格强平检查 (最直接的指标)
    if position['side'] == 'long' and current_price <= position['liquidation_price']:
        return True, f"价格 ({current_price:.4f}) 触及强平线 ({position['liquidation_price']:.4f})"
    if position['side'] == 'short' and current_price >= position['liquidation_price']:
        return True, f"价格 ({current_price:.4f}) 触及强平线 ({position['liquidation_price']:.4f})"

    # 2. 保证金率检查 (核心风险指标)
    margin_ratio = calculate_margin_ratio(position, current_price)
    # 维持保证金率通常是强平保证金率的2倍，这里用10%作为风险警戒线
    if margin_ratio < 0.1:
        return True, f"保证金率 ({margin_ratio:.2%}) 过低，有强平风险"

    # 3. 最大亏损检查 (风控底线)
    pnl = calculate_futures_pnl(position, current_price)
    max_loss = position['margin'] * 0.8  # 允许的最大亏损为保证金的80%
    if pnl < -max_loss:
        return True, f"亏损 ({pnl:.2f}) 超过风险限额 ({-max_loss:.2f})"
        
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