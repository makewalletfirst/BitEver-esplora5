import subprocess
import json
import hashlib
import base58
import time

# RPC 설정 (포트 및 경로 확인 완료)
RPC_CMD = [
    "/root/Bitever/src/bitcoin-cli",
    "-datadir=/root/myfork",
    "-rpcuser=user",
    "-rpcpassword=pass",
    "-rpcport=8334"
]

def pubkey_to_address(pubkey_hex):
    """공개키를 P2PKH 주소로 변환"""
    pubkey_bin = bytes.fromhex(pubkey_hex)
    vh = b'\x00' + hashlib.new('ripemd160', hashlib.sha256(pubkey_bin).digest()).digest()
    checksum = hashlib.sha256(hashlib.sha256(vh).digest()).digest()[:4]
    return base58.b58encode(vh + checksum).decode('utf-8')

def get_p2pk_utxos():
    p2pk_map = {}
    print("블록 스캔을 통해 P2PK Raw Script를 수집합니다. (0~100,000 블록)")
    
    # 10만 번 블록까지 순회
    for height in range(0, 478558):
        if height % 1000 == 0:
            print(f"현재 {height}번 블록 스캔 중... (수집된 주소: {len(p2pk_map)}개)")

        try:
            block_hash = subprocess.check_output(RPC_CMD + ["getblockhash", str(height)]).decode().strip()
            # verbosity 2를 사용하여 트랜잭션 상세 정보를 가져옴
            block_data = json.loads(subprocess.check_output(RPC_CMD + ["getblock", block_hash, "2"]))

            for tx in block_data['tx']:
                for vout in tx['vout']:
                    script = vout['scriptPubKey'].get('hex', '')
                    # P2PK 패턴 판별 (비압축 65바이트 공개키 기준)
                    if len(script) == 134 and script.startswith("41") and script.endswith("ac"):
                        pubkey = script[2:-2]
                        address = pubkey_to_address(pubkey)
                        
                        # 핵심 수정 사항: scripthash 대신 원본 script hex를 저장
                        p2pk_map[address] = script
        except Exception as e:
            continue

    return p2pk_map

if __name__ == "__main__":
    start_time = time.time()
    result_map = get_p2pk_utxos()
    
    with open("p2pk_map.json", "w") as f:
        json.dump(result_map, f, indent=4)
        
    end_time = time.time()
    print(f"완료! 총 {len(result_map)}개의 매핑이 저장되었습니다.")
    print(f"소요 시간: {round(end_time - start_time, 2)}초")

