# -*- coding: utf-8 -*-
import re
import json
from typing import Any, Dict
from astrbot.api import logger

# --- Schema Definitions ---

STRATEGY_SCHEMA = {
    "required": ["strategy", "allocations"],
    "fields": {
        "strategy": {"type": str},
        "risk_level": {"type": str, "default": "medium"},
        "allocations": {
            "type": dict,
            "required": ["spot", "futures", "cash"],
            "fields": {
                "spot": {"type": list, "default": []},
                "futures": {"type": list, "default": []},
                "cash": {"type": (int, float), "min": 0, "max": 100, "default": 100}
            }
        }
    }
}

REBALANCE_SCHEMA = {
    "required": ["analysis", "actions"],
    "fields": {
        "analysis": {"type": str, "default": "无分析"},
        "market_direction": {"type": str, "default": "neutral"},
        "confidence_level": {"type": str, "default": "medium"},
        "time_horizon": {"type": str, "default": "short_term"},
        "actions": {
            "type": list,
            "default": [{"action": "HOLD", "reason": "默认保持仓位"}]
        }
    }
}

PERFORMANCE_SCHEMA = {
    "required": ["performance_rating", "strengths", "weaknesses", "key_learnings", "suggestions"],
    "fields": {
        "performance_rating": {"type": (int, float), "min": 0, "max": 10, "default": 5},
        "strengths": {"type": list, "default": ["无明显优点"]},
        "weaknesses": {"type": list, "default": ["无明显缺点"]},
        "key_learnings": {"type": list, "default": ["需要更多数据进行分析"]},
        "suggestions": {"type": list, "default": ["继续观察市场"]}
    }
}


class AIResponseParser:
    """
    一个健壮的解析器，用于清理、解析、验证和修复来自AI的JSON响应。
    """
    def _clean_json_text(self, text: str) -> str:
        """
        从可能包含 markdown 和其他文本的字符串中提取纯净的JSON字符串。
        """
        # 使用正则表达式查找被 ```json 和 ``` 包裹的内容
        match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
        if match:
            return match.group(1).strip()

        # 如果没有找到 markdown 块，则尝试查找第一个 '{' 或 '[' 到最后一个 '}' 或 ']'
        match = re.search(r'\{[\s\S]*\}|\[[\s\S]*\]', text)
        if match:
            return match.group(0).strip()
            
        return text.strip()

    def _validate_schema(self, data: Dict, schema: Dict) -> bool:
        """
        根据定义的模式递归验证数据的结构、类型和范围。
        """
        if not isinstance(data, dict): return False
        
        for field in schema.get("required", []):
            if field not in data:
                logger.warning(f"Schema验证失败: 缺少必需字段 '{field}'")
                return False

        for field, rules in schema.get("fields", {}).items():
            if field in data:
                value = data[field]
                if "type" in rules and not isinstance(value, rules["type"]):
                    logger.warning(f"Schema验证失败: 字段 '{field}' 类型错误 (期望 {rules['type']}, 得到 {type(value)})")
                    return False
                if "min" in rules and value < rules["min"]:
                    logger.warning(f"Schema验证失败: 字段 '{field}' 的值 {value} 小于最小值 {rules['min']}")
                    return False
                if "max" in rules and value > rules["max"]:
                    logger.warning(f"Schema验证失败: 字段 '{field}' 的值 {value} 大于最大值 {rules['max']}")
                    return False
                # 递归验证嵌套的字典
                if isinstance(value, dict) and "fields" in rules:
                    if not self._validate_schema(value, rules):
                        return False
        return True

    def _get_fallback_response(self, schema: Dict) -> Dict:
        """
        根据模式生成一个安全的降级（默认）响应。
        """
        fallback = {}
        for field, rules in schema.get("fields", {}).items():
            if "default" in rules:
                fallback[field] = rules["default"]
            # 递归为嵌套对象生成降级响应
            elif rules.get("type") is dict and "fields" in rules:
                fallback[field] = self._get_fallback_response(rules)
        return fallback

    def parse(self, completion_text: str, schema: Dict) -> Dict:
        """
        执行完整的解析和验证流程。
        如果成功，返回有效的数据字典；如果失败，返回一个安全的降级字典。
        """
        try:
            cleaned_text = self._clean_json_text(completion_text)
            data = json.loads(cleaned_text)
            
            if self._validate_schema(data, schema):
                return data
            else:
                logger.error("AI响应未能通过Schema验证，将使用降级响应。")
                return self._get_fallback_response(schema)
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}。将使用降级响应。原始文本: '{completion_text[:200]}...'")
            return self._get_fallback_response(schema)
        except Exception as e:
            logger.error(f"解析过程中发生未知错误: {e}。将使用降级响应。")
            return self._get_fallback_response(schema)