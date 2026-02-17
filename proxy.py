import requests
import json
import subprocess
import time
import os
from fastapi import FastAPI

app = FastAPI()

# 설정 변수
ELECTRS_URL = "http://127.0.0.1:3002"
RPC_CMD = ["/root/bitever/src/bitcoin-cli", "-datadir=/root/myfork", "-rpcuser=user", "-rpcpassword=pass", "-rpcport=8334"]
CACHE_FILE = "p2pk_scan_results.json"
P2PK_MAP_FILE = "p2pk_map.json"
CACHE_TTL = 300  # 5분

# 사토시 제네시스 상수
SATOSHI_GENESIS_ADDR = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
SATOSHI_GENESIS_TXID = "4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b"
GENESIS_REWARD_SATS = 5000000000  # 50 BTC (BEC)

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

# 스캔 캐시 로드
if os.path.exists(CACHE_FILE):
    try:
        with open(CACHE_FILE, "r") as f: SCAN_CACHE = json.load(f)
    except: SCAN_CACHE = {}
else: SCAN_CACHE = {}

def get_rpc_data(address):
    now = time.time()
    if address in SCAN_CACHE:
        entry = SCAN_CACHE[address]
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

    # 1. 사토시 제네시스 보정 (UTXO 세트에 없으므로 강제 합산)
    if address == SATOSHI_GENESIS_ADDR:
        if "chain_stats" not in data:
            data["chain_stats"] = {"funded_txo_sum": 0, "tx_count": 0, "spent_txo_sum": 0, "funded_txo_count": 0}
        
        # 제네시스 보상은 spent_txo_sum에 잡히지 않으므로 funded에만 추가
        data["chain_stats"]["funded_txo_sum"] += GENESIS_REWARD_SATS
        data["chain_stats"]["tx_count"] += 1
        data["chain_stats"]["funded_txo_count"] += 1

    # 2. 일반 P2PK 주소 처리 (1번 블록 이후)
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

    # 주소 관련 추가 데이터 처리 (UTXO, TXS)
    if address == SATOSHI_GENESIS_ADDR or address in P2PK_DB:
        # UTXO 목록 요청 시
        if sub_path == "utxo":
            extra_utxos = []
            # 사토시 제네시스 UTXO 강제 추가
            if address == SATOSHI_GENESIS_ADDR:
                extra_utxos.append({
                    "txid": SATOSHI_GENESIS_TXID, "vout": 0, "value": GENESIS_REWARD_SATS,
                    "status": {"confirmed": True, "block_height": 0}
                })
            
            # 기타 P2PK UTXO (scantxoutset 결과)
            utxo_info = get_rpc_data(address)
            if utxo_info:
                for item in utxo_info.get("unspents", []):
                    # 제네시스 TXID는 중복 방지를 위해 제외 (위에서 수동 추가함)
                    if item["txid"] == SATOSHI_GENESIS_TXID: continue
                    extra_utxos.append({
                        "txid": item["txid"], "vout": item["vout"], "value": int(item["amount"] * 100000000),
                        "status": {"confirmed": True, "block_height": item["height"]}
                    })
            return electrs_data + extra_utxos

        # 트랜잭션 목록 요청 시
        if sub_path == "txs":
            extra_txs = []
            target_txids = []
            
            if address == SATOSHI_GENESIS_ADDR: target_txids.append(SATOSHI_GENESIS_TXID)
            
            utxo_info = get_rpc_data(address)
            if utxo_info:
                for item in utxo_info.get("unspents", []):
                    if item["txid"] not in target_txids: target_txids.append(item["txid"])

            for txid in target_txids:
                try:
                    # 제네시스는 getrawtransaction으로 안 나오므로 예외 처리
                    if txid == SATOSHI_GENESIS_TXID:
                        # 하드코딩된 제네시스 트랜잭션 구조 (최소한의 정보)
                        extra_txs.append({
                            "txid": SATOSHI_GENESIS_TXID, "version": 1, "locktime": 0,
                            "vin": [{"coinbase": "04ffff001d0104455468652054696d65732030332f4a616e2f32303039204368616e63656c6c6f72206f6e206272696e6b206f66207365636f6e64206261696c6f757420666f722062616e6b73", "sequence": 4294967295}],
                            "vout": [{"value": GENESIS_REWARD_SATS, "scriptpubkey": P2PK_DB.get(SATOSHI_GENESIS_ADDR, ""), "scriptpubkey_type": "p2pk", "scriptpubkey_address": SATOSHI_GENESIS_ADDR}],
                            "status": {"confirmed": True, "block_height": 0, "block_hash": "000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f"},
                            "fee": 0
                        })
                        continue

                    raw_tx = subprocess.check_output(RPC_CMD + ["getrawtransaction", txid, "1"])
                    tx_data = json.loads(raw_tx)
                    for vout in tx_data.get("vout", []):
                        if "value" in vout: vout["value"] = int(vout["value"] * 100000000)
                    
                    extra_txs.append({
                        "txid": tx_data["txid"], "version": tx_data["version"], "locktime": tx_data["locktime"],
                        "vin": tx_data["vin"], "vout": tx_data["vout"],
                        "status": {"confirmed": True, "block_height": tx_data.get("blockheight", 0), "block_hash": tx_data.get("blockhash")},
                        "fee": 0
                    })
                except: continue
            return electrs_data + extra_txs

    return electrs_data
