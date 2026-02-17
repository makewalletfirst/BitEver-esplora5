import subprocess
import json
import hashlib
import base58
import time
import os

RPC_CMD = [
    "/home/makewalletfirst/bitever/src/bitcoin-cli",
    "-datadir=/home/makewalletfirst/myfork",
    "-rpcuser=user",
    "-rpcpassword=pass",
    "-rpcport=8334"
]

STATUS_FILE = "scan_status.json"
MAP_FILE = "p2pk_map.json"

def pubkey_to_address(pubkey_hex):
    pubkey_bin = bytes.fromhex(pubkey_hex)
    vh = b'\x00' + hashlib.new('ripemd160', hashlib.sha256(pubkey_bin).digest()).digest()
    checksum = hashlib.sha256(hashlib.sha256(vh).digest()).digest()[:4]
    return base58.b58encode(vh + checksum).decode('utf-8')

def get_last_height():
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE, "r") as f:
            return json.load(f).get("last_height", 0)
    return 0

def save_status(height):
    with open(STATUS_FILE, "w") as f:
        json.dump({"last_height": height, "updated_at": time.ctime()}, f)

def update_p2pk_map():
    # 1. 기존 매핑 로드
    if os.path.exists(MAP_FILE):
        with open(MAP_FILE, "r") as f: p2pk_map = json.load(f)
    else: p2pk_map = {}

    # 2. 스캔 범위 설정
    start_height = get_last_height() + 1
    try:
        current_height = int(subprocess.check_output(RPC_CMD + ["getblockcount"]).decode().strip())
    except:
        print("RPC 연결 실패"); return

    if start_height > current_height:
        print(f"이미 최신 상태입니다. (Height: {current_height})")
        return

    print(f"스캔 시작: {start_height} -> {current_height}")

    # 3. 증분 스캔 루프
    for height in range(start_height, current_height + 1):
        if height % 1000 == 0:
            print(f"현재 {height}번 블록 스캔 중... (수집된 총 주소: {len(p2pk_map)}개)")

        try:
            block_hash = subprocess.check_output(RPC_CMD + ["getblockhash", str(height)]).decode().strip()
            block_data = json.loads(subprocess.check_output(RPC_CMD + ["getblock", block_hash, "2"]))

            for tx in block_data['tx']:
                for vout in tx['vout']:
                    script = vout['scriptPubKey'].get('hex', '')
                    # P2PK 패턴 판별 (비압축 65바이트 또는 압축 33바이트)
                    is_p2pk = False
                    if len(script) == 134 and script.startswith("41") and script.endswith("ac"): # Uncompressed
                        pubkey = script[2:-2]
                        is_p2pk = True
                    elif len(script) == 70 and script.startswith("21") and script.endswith("ac"): # Compressed
                        pubkey = script[2:-2]
                        is_p2pk = True
                    
                    if is_p2pk:
                        address = pubkey_to_address(pubkey)
                        p2pk_map[address] = script
        except:
            continue

    # 4. 결과 저장
    with open(MAP_FILE, "w") as f:
        json.dump(p2pk_map, f, indent=4)
    save_status(current_height)
    print(f"업데이트 완료! 현재 총 {len(p2pk_map)}개 주소 매핑됨.")

if __name__ == "__main__":
    update_p2pk_map()
