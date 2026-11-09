# -*- coding: utf-8 -*-
"""被测对象：客服 Agent（v3：system prompt + 修 cancel_order 漏洞 + key 独立存放）

读 key 的顺序（不会再被覆盖）：
    1. 环境变量 DEEPSEEK_API_KEY
    2. 本目录下的 key.txt  ← 推荐：新建一个 key.txt，里面只写一行 sk-xxxx

v3 相对 v2 改了两处：
    1. 新增 SYSTEM_PROMPT：多步任务必须做完 / 明确金额优先 / 不许编造 / 缺参数先问
    2. cancel_order 原来只拦「已发货」，已签收也能取消 —— 业务漏洞，已修
"""
import json
import os

from openai import OpenAI

MODEL = "deepseek-chat"
BASE_URL = "https://api.deepseek.com"
HERE = os.path.dirname(os.path.abspath(__file__))


def _load_key():
    key = (os.environ.get("DEEPSEEK_API_KEY") or "sk-3d6db39f546a41c5ad6371ef437f920e").strip()
    if key:
        return key
    path = os.path.join(HERE, "key.txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            return f.read().strip()
    return ""


API_KEY = _load_key()

# ------------------------------------------------------------------
# v3 新增：系统提示词。这 11 条规则，每一条都对着一条失败用例去写的
# ------------------------------------------------------------------
SYSTEM_PROMPT = """你是电商客服助手。所有查询和操作都必须通过工具完成，不要凭印象回答。

【必须调用工具】
1. 用户要查订单状态/金额、退款、取消订单时，必须调用对应工具，不要直接报答案。
2. 用户一句话里提出多个操作（例如「看看 A1001 然后退 30」「把 A1001 和 A1002 都退了」），
   必须把每一个操作都真正执行完，不能只查不办，也不能只办第一个。

【参数规则】
3. 缺订单号：先追问订单号，不要猜。
4. 缺退款金额：先追问金额，绝对不要默认填 0、全额或任何数字。
5. 用户在任意一轮已经明确说过的数字（例如「退 100」），优先于你自己推算的金额；
   只有用户说「全退」「退一半」这类相对说法时，才用工具返回的订单金额去算。
6. 中文金额要换算成数字：九十九块九毛 = 99.9，一半 = 订单金额 / 2。

【回答规则】
7. 只陈述工具真正返回过的信息。到账时间、退款单号、物流单号、预计送达时间这类
   工具没有返回的内容，一律不要编造；可以说「以原支付渠道为准，具体请查官方通知」。
8. 工具返回 error 时如实转述原因（例如「查不到订单」「退款金额超过订单金额」
   「已发货不能取消」），绝不能声称办理成功。
9. 与订单无关的问题（问候、闲聊、天气、写诗、上下班时间），直接用文字回答，
   不要调用任何工具。

【业务规则】
10. 待发货：可以取消，也可以退款。
11. 已发货 / 已签收：不能取消，只能走退款。"""

ORDERS = {
    "A1001": {"status": "已发货", "amount": 129.0},
    "A1002": {"status": "待发货", "amount": 39.9},
    "B2001": {"status": "已签收", "amount": 688.0},
}


# ---------------- 工具实现 ----------------
def get_order_status(order_id: str) -> dict:
    if order_id not in ORDERS:
        return {"error": f"查不到订单 {order_id}"}
    return {"order_id": order_id, **ORDERS[order_id]}


def refund(order_id: str, amount: float) -> dict:
    if order_id not in ORDERS:
        return {"error": f"查不到订单 {order_id}"}
    if amount <= 0:
        return {"error": "退款金额必须大于 0"}
    if amount > ORDERS[order_id]["amount"]:
        return {"error": "退款金额超过订单金额"}
    return {"ok": True, "order_id": order_id, "refunded": amount}


def cancel_order(order_id: str) -> dict:
    if order_id not in ORDERS:
        return {"error": f"查不到订单 {order_id}"}
    # v3 修复：已签收也属于不可取消（原来只拦了已发货）
    if ORDERS[order_id]["status"] in ("已发货", "已签收"):
        return {"error": f"订单{ORDERS[order_id]['status']}，无法取消，请走退款"}
    return {"ok": True, "order_id": order_id, "cancelled": True}


FUNCS = {
    "get_order_status": get_order_status,
    "refund": refund,
    "cancel_order": cancel_order,
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_order_status",
            "description": "查询订单的状态和金额。用户问订单进展、多少钱时调用。",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string", "description": "订单号，例如 A1001"}},
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "refund",
            "description": "对某个订单发起退款。用户明确要求退款、退钱、退货退款时调用。金额必须是用户说过的数字或按规则算出的数字。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单号"},
                    "amount": {"type": "number", "description": "退款金额，单位元"},
                },
                "required": ["order_id", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_order",
            "description": "取消尚未发货的订单。用户说取消、不要了、撤单时调用。已发货或已签收的订单不能取消。",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string", "description": "订单号"}},
                "required": ["order_id"],
            },
        },
    },
]


def make_client():
    if not API_KEY:
        raise RuntimeError(
            "没有 API Key。两种办法：\n"
            f"  1) 在本目录新建 key.txt，里面只写一行 sk-xxxx（推荐，不会被覆盖）\n"
            f"     路径：{os.path.join(HERE, 'key.txt')}\n"
            "  2) 或者设置环境变量 DEEPSEEK_API_KEY"
        )
    return OpenAI(api_key=API_KEY, base_url=BASE_URL)


class Talk:
    """一轮会话。连续调用 send() 就是多轮对话。"""

    def __init__(self, client=None, use_system_prompt=True):
        self.client = client or make_client()
        # v3：第一句就是 system prompt
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}] if use_system_prompt else []
        self.tool_calls = []      # [{"name":..., "args":..., "result":...}]
        self.answers = []         # 每一轮的最终回答

    def send(self, text, max_steps=6):
        self.messages.append({"role": "user", "content": text})
        for _ in range(max_steps):
            resp = self.client.chat.completions.create(
                model=MODEL, messages=self.messages, tools=TOOLS, tool_choice="auto"
            )
            msg = resp.choices[0].message

            if not msg.tool_calls:
                answer = msg.content or ""
                self.answers.append(answer)
                return {"answer": answer, "tool_calls": self.tool_calls}

            self.messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ],
            })

            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                    result = {"error": "参数不是合法 JSON"}
                else:
                    if name not in FUNCS:
                        result = {"error": f"不存在的工具 {name}"}
                    else:
                        try:
                            result = FUNCS[name](**args)
                        except Exception as exc:
                            result = {"error": f"{type(exc).__name__}: {exc}"}

                self.tool_calls.append({"name": name, "args": args, "result": result})
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

        answer = "[超过最大轮数，模型还在调工具]"
        self.answers.append(answer)
        return {"answer": answer, "tool_calls": self.tool_calls}
