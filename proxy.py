import requests
import json
import subprocess
import time
import os
from fastapi import FastAPI

app = FastAPI()

ELECTRS_URL = "http://127.0.0.1:3002"
RPC_CMD = ["/root/Bitever/src/bitcoin-cli", "-datadir=/root/myfork", "-rpcuser=user", "-rpcpassword=pass", "-rpcport=8334"]
CACHE_FILE = "p2pk_scan_results.json"
P2PK_MAP_FILE = "p2pk_map.json"
CACHE_TTL = 300  # 5분마다 갱신 허용 (성능과 최신성 사이의 타협점)

P2PK_DB = {}
LAST_MTIME = 0

def reload_p2pk_db():
    global P2PK_DB, LAST_MTIME
    if not os.path.exists(P2PK_MAP_FILE): return
    try:
        current_mtime = os.path.getmtime(P2PK_MAP_FILE)
        if current_mtime > LAST_MTIME:
            with open(P2PK_MAP_FILE, "r") as f: P2PK_DB = json.load(f)
            LAST_MTIME = current_mtime
            print(f"[{time.ctime()}] P2PK DB 업데이트 완료 ({len(P2PK_DB)} keys)")
    except Exception as e: print(f"P2PK DB 로드 오류: {e}")

reload_p2pk_db()

# 스캔 캐시 로드 로직 수정 (구조 변경 대응)
if os.path.exists(CACHE_FILE):
    try:
        with open(CACHE_FILE, "r") as f: SCAN_CACHE = json.load(f)
    except: SCAN_CACHE = {}
else: SCAN_CACHE = {}

def get_rpc_data(address):
    now = time.time()
    
    # 캐시 확인 (새로운 구조: {"timestamp": ..., "data": ...})
    if address in SCAN_CACHE:
        entry = SCAN_CACHE[address]
        # 과거 데이터 형식(timestamp 없음)이거나 TTL이 만료된 경우 재스캔
        if isinstance(entry, dict) and now - entry.get("timestamp", 0) < CACHE_TTL:
            return entry.get("data")

    raw_script = P2PK_DB.get(address)
    if not raw_script: return None

    try:
        subprocess.run(RPC_CMD + ["scantxoutset", "abort"], capture_output=True)
        time.sleep(0.3)
        rpc_res = subprocess.check_output(RPC_CMD + ["scantxoutset", "start", f'["raw({raw_script})"]'])
        result = json.loads(rpc_res)
        
        if result.get("success"):
            SCAN_CACHE[address] = {"timestamp": now, "data": result}
            with open(CACHE_FILE, "w") as f: json.dump(SCAN_CACHE, f, indent=4)
            return result
    except: return None
    return None

@app.get("/api/address/{address}")
async def get_address(address: str):
    reload_p2pk_db()
    resp = requests.get(f"{ELECTRS_URL}/address/{address}")
    data = resp.json()
    if address in P2PK_DB:
        utxo_info = get_rpc_data(address)
        if utxo_info:
            p2pk_satoshis = int(utxo_info.get("total_amount", 0) * 100000000)
            p2pk_tx_count = len(utxo_info.get("unspents", []))
            if "chain_stats" not in data:
                data["chain_stats"] = {"funded_txo_sum": 0, "tx_count": 0, "spent_txo_sum": 0, "funded_txo_count": 0}
            data["chain_stats"]["funded_txo_sum"] += p2pk_satoshis
            data["chain_stats"]["tx_count"] += p2pk_tx_count
            data["scripthash"] = P2PK_DB[address]
    return data

@app.get("/api/address/{address}/{sub_path:path}")
async def proxy_address_subpath(address: str, sub_path: str):
    reload_p2pk_db()
    resp = requests.get(f"{ELECTRS_URL}/address/{address}/{sub_path}")
    try: electrs_data = resp.json()
    except: electrs_data = []
    if address in P2PK_DB:
        utxo_info = get_rpc_data(address)
        if not utxo_info: return electrs_data
        if sub_path == "utxo":
            p2pk_utxos = [{
                "txid": item["txid"], "vout": item["vout"], "value": int(item["amount"] * 100000000),
                "status": {"confirmed": True, "block_height": item["height"]}
            } for item in utxo_info.get("unspents", [])]
            return electrs_data + p2pk_utxos
        if sub_path == "txs":
            p2pk_txs = []
            for item in utxo_info.get("unspents", []):
                try:
                    raw_tx = subprocess.check_output(RPC_CMD + ["getrawtransaction", item["txid"], "1"])
                    tx_data = json.loads(raw_tx)
                    for vout in tx_data.get("vout", []):
                        if "value" in vout: vout["value"] = int(vout["value"] * 100000000)
                    p2pk_txs.append({
                        "txid": tx_data["txid"], "version": tx_data["version"], "locktime": tx_data["locktime"],
                        "vin": tx_data["vin"], "vout": tx_data["vout"],
                        "status": {"confirmed": True, "block_height": item["height"], "block_hash": tx_data.get("blockhash")},
                        "fee": 0, "sigops": 1
                    })
                except: continue
            return electrs_data + p2pk_txs
    return electrs_data
