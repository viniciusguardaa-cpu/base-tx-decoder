#!/usr/bin/env python3
"""Base Tx Decoder — x402-gated Base chain transaction decoder."""
import json, os, time, urllib.request, urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = int(os.environ.get("PORT", "8850"))
PAY_TO = "0x65aa59025C4AcD8CD7ba2051ecb9152abaE4fcC6"
PRICE_USDC = 0.002
PRICE_UNITS = int(PRICE_USDC * 1e6)
CHAIN_ID = 8453
ASSET = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
USED_TXS_FILE = os.path.join(os.path.dirname(__file__), "used_txs.json")
RPC = "https://mainnet.base.org"

def load_used_txs():
    try:
        with open(USED_TXS_FILE) as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def save_used_txs(s):
    with open(USED_TXS_FILE, "w") as f:
        json.dump(sorted(s), f)

def fetch_json(url, timeout=10, headers=None):
    h = {"User-Agent": "base-tx-decoder/1.0"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def rpc_call(method, params, timeout=15):
    payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
    req = urllib.request.Request(RPC, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def get_tx(tx_hash):
    tx = rpc_call("eth_getTransactionByHash", [tx_hash]).get("result")
    if not tx:
        return None, "tx_not_found"
    receipt = rpc_call("eth_getTransactionReceipt", [tx_hash]).get("result")
    block = None
    if tx.get("blockNumber"):
        block = rpc_call("eth_getBlockByNumber", [tx["blockNumber"], False]).get("result")
    func_sig = None
    sel = tx.get("input", "0x")[:10]
    if sel and sel != "0x" and len(sel) == 10:
        try:
            data = fetch_json(f"https://www.4byte.directory/api/v1/signatures/?hex_signature={sel}")
            res = data.get("results", [])
            if res:
                func_sig = res[0].get("text_signature")
        except Exception:
            pass
    transfers = []
    if receipt:
        for log in receipt.get("logs", []):
            topics = log.get("topics", [])
            if len(topics) >= 3 and topics[0].lower() == "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef":
                try:
                    transfers.append({
                        "token": log.get("address"),
                        "from": "0x" + topics[1][-40:],
                        "to": "0x" + topics[2][-40:],
                        "amount": str(int(log.get("data", "0x0"), 16)),
                    })
                except Exception:
                    pass
    value_wei = int(tx.get("value", "0x0"), 16)
    gas_price = int(tx.get("gasPrice", "0x0"), 16) if tx.get("gasPrice") else None
    gas_used = int(receipt.get("gasUsed", "0x0"), 16) if receipt else None
    return {
        "tx_hash": tx_hash,
        "from": tx.get("from"),
        "to": tx.get("to"),
        "value_eth": value_wei / 1e18,
        "value_wei": value_wei,
        "gas_price_gwei": (gas_price / 1e9) if gas_price else None,
        "gas_used": gas_used,
        "gas_cost_eth": (gas_price * gas_used / 1e18) if (gas_price and gas_used) else None,
        "nonce": int(tx.get("nonce", "0x0"), 16),
        "input_selector": sel,
        "function": func_sig,
        "block_number": int(tx["blockNumber"], 16) if tx.get("blockNumber") else None,
        "block_timestamp": int(block.get("timestamp", "0x0"), 16) if block else None,
        "status": "success" if (receipt and receipt.get("status") == "0x1") else ("failed" if receipt else "pending"),
        "contract_created": receipt.get("contractAddress") if receipt else None,
        "erc20_transfers": transfers,
        "decoded_at": int(time.time()),
    }, None

def verify_tx(tx_hash):
    payload = json.dumps({"jsonrpc": "2.0", "method": "eth_getTransactionReceipt", "params": [tx_hash], "id": 1}).encode()
    req = urllib.request.Request(RPC, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode())
    receipt = data.get("result")
    if not receipt or receipt.get("status") != "0x1":
        return False, "tx_not_found_or_failed"
    for log in receipt.get("logs", []):
        if log.get("address", "").lower() == ASSET.lower():
            topics = log.get("topics", [])
            if len(topics) >= 3 and topics[0].lower() == "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef":
                to_addr = "0x" + topics[2][-40:]
                if to_addr.lower() == PAY_TO.lower():
                    amount = int(log.get("data", "0x0"), 16)
                    if amount >= PRICE_UNITS:
                        return True, "verified"
    return False, "no_matching_transfer"

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        if path == "/health":
            self.send_json(200, {"status": "ok", "service": "base-tx-decoder", "price_usdc": PRICE_USDC, "chain": "base", "endpoints": ["/health", "/decode?tx=0x..."]})
            return

        tx_hash = self.headers.get("X-Payment-Tx", "").strip()
        if not tx_hash:
            self.send_json(402, {"error": "payment_required", "message": f"Pay {PRICE_USDC} USDC on Base to {PAY_TO}",
                "pay_to": PAY_TO, "asset": ASSET, "chain": "base", "chain_id": CHAIN_ID,
                "amount_usdc": PRICE_USDC, "amount_units": PRICE_UNITS,
                "instructions": "Send USDC on Base to pay_to, then retry with X-Payment-Tx: <tx_hash>"})
            return

        used = load_used_txs()
        if tx_hash in used:
            self.send_json(402, {"error": "tx_already_used"})
            return
        ok, reason = verify_tx(tx_hash)
        if not ok:
            self.send_json(402, {"error": "payment_not_verified", "reason": reason})
            return
        used.add(tx_hash)
        save_used_txs(used)

        try:
            if path == "/decode":
                h = params.get("tx", [""])[0].strip()
                if not h or not h.startswith("0x") or len(h) != 66:
                    self.send_json(400, {"error": "missing_or_invalid_tx", "usage": "/decode?tx=0x<64 hex>"})
                    return
                result, err = get_tx(h)
                if err:
                    self.send_json(404, {"error": err, "tx": h})
                    return
                self.send_json(200, result)
            else:
                self.send_json(404, {"error": "not_found", "endpoints": ["/health", "/decode?tx=0x..."]})
        except Exception as e:
            self.send_json(500, {"error": "internal_error", "message": str(e)})

    def send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass

if __name__ == "__main__":
    print(f"Base Tx Decoder starting on port {PORT}")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
