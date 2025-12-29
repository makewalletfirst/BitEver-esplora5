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

# 매핑 및 캐시 로드
try:
    with open("p2pk_map.json", "r") as f: P2PK_DB = json.load(f)
except: P2PK_DB = {}

if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, "r") as f: SCAN_CACHE = json.load(f)
else: SCAN_CACHE = {}

def get_rpc_data(address):
    if address in SCAN_CACHE: return SCAN_CACHE[address]
    raw_script = P2PK_DB.get(address)
    if not raw_script: return None
    try:
        subprocess.run(RPC_CMD + ["scantxoutset", "abort"], capture_output=True)
        time.sleep(0.3)
        rpc_res = subprocess.check_output(RPC_CMD + ["scantxoutset", "start", f'["raw({raw_script})"]'])
        result = json.loads(rpc_res)
        if result.get("success"):
            SCAN_CACHE[address] = result
            with open(CACHE_FILE, "w") as f: json.dump(SCAN_CACHE, f, indent=4)
            return result
    except: return None
    return None

@app.get("/api/address/{address}")
async def get_address(address: str):
    # 1. Electrs에서 기본 데이터를 가져옴 (최신 11 BEC 정보가 들어있음)
    resp = requests.get(f"{ELECTRS_URL}/address/{address}")
    data = resp.json()

    if address in P2PK_DB:
        utxo_info = get_rpc_data(address)
        if utxo_info:
            p2pk_satoshis = int(utxo_info.get("total_amount", 0) * 100000000)
            p2pk_tx_count = len(utxo_info.get("unspents", []))
            
            # 데이터 병합: Electrs 데이터 + 과거 P2PK 데이터
            if "chain_stats" not in data: data["chain_stats"] = {"funded_txo_sum": 0, "tx_count": 0, "spent_txo_sum": 0, "funded_txo_count": 0}
            
            data["chain_stats"]["funded_txo_sum"] += p2pk_satoshis
            data["chain_stats"]["tx_count"] += p2pk_tx_count
            data["scripthash"] = P2PK_DB[address]
    return data

@app.get("/api/address/{address}/{sub_path:path}")
async def proxy_address_subpath(address: str, sub_path: str):
    # 1. 먼저 Electrs의 데이터를 가져옴
    resp = requests.get(f"{ELECTRS_URL}/address/{address}/{sub_path}")
    try: electrs_data = resp.json()
    except: electrs_data = []

    if address in P2PK_DB:
        utxo_info = get_rpc_data(address)
        if not utxo_info: return electrs_data

        # UTXO 병합
        if sub_path == "utxo":
            p2pk_utxos = [{
                "txid": item["txid"], "vout": item["vout"], "value": int(item["amount"] * 100000000),
                "status": {"confirmed": True, "block_height": item["height"]}
            } for item in utxo_info.get("unspents", [])]
            return electrs_data + p2pk_utxos

        # 트랜잭션 리스트 병합
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
            # 최신 트랜잭션이 위로 오게 병합 (Electrs 데이터가 보통 최신)
            return electrs_data + p2pk_txs

    return electrs_data

