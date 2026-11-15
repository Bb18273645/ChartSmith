# Copyright (c) 2026 Bb18273645.
# SPDX-License-Identifier: AGPL-3.0-or-later
# 本作品以 AGPL-3.0-or-later 授权；闭源商业使用需另行取得商业许可，详见 COMMERCIAL-LICENSE.md。
"""预览用的示例结构，顺便当 JSON 契约的可复制样例。"""

from __future__ import annotations

LOGIN = {
    "title": "登录流程",
    "subtitle": "手机号 + 密码，JWT 会话",
    "direction": "TB",
    "nodes": [
        {"id": "user", "label": "用户", "sub": "App / Web"},
        {"id": "web", "label": "前端", "sub": "React", "tone": "brand"},
        {"id": "gw", "label": "网关", "sub": "Nginx", "tone": "brand"},
        {"id": "auth", "label": "认证服务", "sub": "签发 JWT", "tone": "success"},
        {"id": "db", "label": "用户库", "sub": "PostgreSQL", "tone": "info"},
    ],
    "edges": [
        {"from": "user", "to": "web", "label": "点击登录"},
        {"from": "web", "to": "gw", "label": "POST /login"},
        {"from": "gw", "to": "auth", "label": "转发"},
        {"from": "auth", "to": "db", "label": "查用户"},
        {"from": "db", "to": "auth", "label": "返回", "style": "dashed"},
    ],
}

MICROSERVICES = {
    "title": "订单系统架构",
    "subtitle": "主干链路，其余服务按领域分组",
    "direction": "TB",
    "nodes": [
        {"id": "gw", "label": "网关", "sub": "Nginx", "tone": "brand"},
        {"id": "auth", "label": "认证", "sub": "JWT", "tone": "success"},
        {"id": "order", "label": "订单服务", "sub": "FastAPI", "tone": "brand"},
        {"id": "pay", "label": "支付服务", "sub": "gRPC", "tone": "info"},
        {"id": "mq", "label": "消息队列", "sub": "Kafka", "tone": "warn"},
        {"id": "inv", "label": "库存服务", "sub": "Go", "tone": "neutral"},
        {"id": "notify", "label": "通知服务", "sub": "SMS / Push", "tone": "neutral"},
        {"id": "db", "label": "订单库", "sub": "MySQL", "tone": "info"},
        {"id": "cache", "label": "缓存", "sub": "Redis", "tone": "neutral"},
    ],
    "edges": [
        {"from": "gw", "to": "auth"},
        {"from": "gw", "to": "order", "label": "下单"},
        {"from": "order", "to": "cache", "label": "读缓存"},
        {"from": "order", "to": "db", "label": "写订单"},
        {"from": "order", "to": "pay", "label": "扣款"},
        {"from": "pay", "to": "mq", "label": "支付成功"},
        {"from": "mq", "to": "inv", "label": "锁定库存"},
        {"from": "mq", "to": "notify", "label": "发通知"},
        {"from": "mq", "to": "order", "label": "补偿重试", "style": "dashed"},
    ],
}

ETL_LR = {
    "title": "数据同步链路",
    "subtitle": "方向 LR，适合宽屏",
    "direction": "LR",
    "nodes": [
        {"id": "src", "label": "业务库", "sub": "MySQL", "tone": "neutral"},
        {"id": "ext", "label": "抽取", "sub": "DataX", "tone": "brand"},
        {"id": "tr", "label": "清洗转换", "sub": "Spark", "tone": "info"},
        {"id": "dim", "label": "维度表", "sub": "Hive", "tone": "neutral"},
        {"id": "load", "label": "装载", "sub": "Doris", "tone": "success"},
        {"id": "bi", "label": "报表", "sub": "BI 看板", "tone": "neutral"},
    ],
    "edges": [
        {"from": "src", "to": "ext", "label": "增量"},
        {"from": "ext", "to": "tr", "label": "原始层"},
        {"from": "tr", "to": "dim", "label": "关联"},
        {"from": "dim", "to": "load"},
        {"from": "tr", "to": "load", "label": "事实表"},
        {"from": "load", "to": "bi", "label": "查询"},
    ],
}

ORDER_STATES = {
    "title": "订单状态机",
    "subtitle": "带环，回边会绕外侧走",
    "direction": "TB",
    "nodes": [
        {"id": "created", "label": "已创建", "tone": "neutral"},
        {"id": "paid", "label": "已支付", "tone": "success"},
        {"id": "shipped", "label": "已发货", "tone": "info"},
        {"id": "done", "label": "已完成", "tone": "success"},
        {"id": "canceled", "label": "已取消", "tone": "error"},
        {"id": "after", "label": "售后中", "tone": "warn"},
    ],
    "edges": [
        {"from": "created", "to": "paid", "label": "支付成功"},
        {"from": "created", "to": "canceled", "label": "超时"},
        {"from": "paid", "to": "shipped", "label": "出库"},
        {"from": "shipped", "to": "done", "label": "签收"},
        {"from": "done", "to": "after", "label": "申请售后", "style": "dashed"},
        {"from": "after", "to": "paid", "label": "补差价重付", "style": "dashed"},
    ],
}

TRIMMED = {
    "title": "超限裁剪",
    "subtitle": "20 个节点，超过上限 16",
    "direction": "TB",
    "nodes": [{"id": f"s{i}", "label": f"服务{i:02d}", "tone": "neutral"} for i in range(1, 21)],
    "edges": [{"from": f"s{i}", "to": f"s{i + 1}", "label": "调用"} for i in range(1, 20)],
}

DEPLOY_STATUS = {
    "title": "发布流水线 ✅",
    "subtitle": "emoji 会被换成字体里有的符号",
    "direction": "TB",
    "nodes": [
        {"id": "ci", "label": "✅ 构建通过", "sub": "CI", "tone": "success"},
        {"id": "test", "label": "✅ 单测通过", "sub": "pytest", "tone": "success"},
        {"id": "scan", "label": "⚠ 安全扫描", "sub": "3 个中危", "tone": "warn"},
        {"id": "approve", "label": "人工审批", "sub": "🚀 待发布", "tone": "brand"},
        {"id": "deploy", "label": "❌ 灰度失败", "sub": "5% 流量", "tone": "error"},
    ],
    "edges": [
        {"from": "ci", "to": "test", "label": "产物"},
        {"from": "test", "to": "scan", "label": "通过"},
        {"from": "scan", "to": "approve", "label": "放行"},
        {"from": "approve", "to": "deploy", "label": "上线"},
    ],
}

SAMPLES = {
    "01-login": LOGIN,
    "02-microservices": MICROSERVICES,
    "03-etl-lr": ETL_LR,
    "04-order-states": ORDER_STATES,
    "05-trimmed": TRIMMED,
    "06-status": DEPLOY_STATUS,
}
