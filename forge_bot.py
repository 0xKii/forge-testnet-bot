#!/usr/bin/env python3
"""
Forge Testnet Automation Bot
=============================
Chain: Bittensor EVM Testnet (chainId: 945)
RPC:  https://test.chain.opentensor.ai

Steps:
  1. Faucet TAO (2captcha) → SS58 address
  2. Bridge native TAO → EVM (if substrate mnemonic provided)
  3. Wrap TAO → wsTAO
  4. Supply wsTAO to Forge
  5. Borrow from Forge

Wallet format (.env → WALLETS):
  [{"pk":"0x...","sub_mnemonic":"word1 word2 ..."}, ...]
  
  - pk: EVM private key (REQUIRED)
  - sub_mnemonic: Substrate wallet mnemonic (OPTIONAL — for bridge)
    If omitted, skips bridge step (claim faucet only, user bridges manually)

Usage:
  python forge_bot.py              # Run all wallets once
  python forge_bot.py --loop       # Loop every 24 hours
"""

import os, sys, json, time
from typing import Optional
from dotenv import load_dotenv

import requests
from eth_account import Account
from web3 import Web3
from substrateinterface import Keypair as SubKeypair

load_dotenv()

# =====================================================================
# CHAIN CONFIG
# =====================================================================
CHAIN_ID = 945
RPC_URL = "https://test.chain.opentensor.ai"
EXPLORER = "https://evm-testscan.dev.opentensor.ai"

WTAO        = Web3.to_checksum_address("0x757bbFffe6f08FEbBE19638833FfADaa7B369C25")
WSTAO       = Web3.to_checksum_address("0xcff46eb93307ca7E24A7cE2A1Eb0F485A27D461a")
UNITROLLER  = Web3.to_checksum_address("0x999C6a7ee03aE0C0a18503C2ECA0C8d5a9f69f31")
VWSTAO      = Web3.to_checksum_address("0x782E5a6Dc16901ec13D4D1e450A8270F4e6E75cf")
FAUCET_EVM  = Web3.to_checksum_address("0x35c23b26B3A6bF06a5ECdD7420e800dB7c7866Fe")
FAUCET_API  = "https://api.taoswap.org/testnet-faucet"

RECAPTCHA_SITE_KEY = "6Ld0ZokrAAAAAAeIFmZpOZJ1dII3zY0Jkl6kUTdR"
RECAPTCHA_PAGE_URL = "https://taoswap.org/testnet-faucet"
LOOP_INTERVAL = 86400  # 24 jam

# =====================================================================
# ABIs
# =====================================================================
ERC20_ABI = json.loads('[{"constant":false,"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"},{"constant":true,"inputs":[{"name":"owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"constant":true,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"stateMutability":"view","type":"function"}]')
FAUCET_ABI = json.loads('[{"inputs":[{"name":"recipient","type":"address"}],"name":"drip","outputs":[{"name":"","type":"uint256"}],"stateMutability":"nonpayable","type":"function"},{"inputs":[],"name":"dripAll","outputs":[],"stateMutability":"nonpayable","type":"function"}]')
COMPTROLLER_ABI = json.loads('[{"constant":false,"inputs":[{"name":"vTokens","type":"address[]"}],"name":"enterMarkets","outputs":[{"name":"","type":"uint256[]"}],"stateMutability":"nonpayable","type":"function"}]')
VTOKEN_ABI = json.loads('[{"constant":false,"inputs":[{"name":"amount","type":"uint256"}],"name":"mint","outputs":[{"name":"","type":"uint256"}],"stateMutability":"nonpayable","type":"function"},{"constant":false,"inputs":[{"name":"borrowAmount","type":"uint256"}],"name":"borrow","outputs":[{"name":"","type":"uint256"}],"stateMutability":"nonpayable","type":"function"},{"constant":true,"inputs":[{"name":"owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"constant":true,"inputs":[],"name":"exchangeRateStored","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]')
BRIDGE_ABI = json.loads('[{"inputs":[{"name":"to","type":"address"},{"name":"amount","type":"uint256"}],"name":"bridge","outputs":[],"stateMutability":"nonpayable","type":"function"}]')

# =====================================================================
# 2CAPTCHA
# =====================================================================
def solve_recaptcha(api_key: str) -> Optional[str]:
    print("  🤖 Solving reCAPTCHA...", end=" ", flush=True)
    r = requests.post("https://2captcha.com/in.php", data={
        "key": api_key, "method": "userrecaptcha",
        "googlekey": RECAPTCHA_SITE_KEY, "pageurl": RECAPTCHA_PAGE_URL, "json": 1,
    }, timeout=30)
    data = r.json()
    if data.get("status") != 1:
        print(f"❌ {data.get('request', 'unknown')}")
        return None
    rid = data["request"]
    print(f"submitted", end=" ", flush=True)
    for i in range(24):
        time.sleep(5)
        r = requests.get("https://2captcha.com/res.php", params={
            "key": api_key, "action": "get", "id": rid, "json": 1,
        }, timeout=10)
        d = r.json()
        if d.get("status") == 1:
            print("✅")
            return d["request"]
        print(".", end="", flush=True)
    print("❌ timeout")
    return None

# =====================================================================
# BLOCKCHAIN
# =====================================================================
def init_web3():
    w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 60}))
    assert w3.is_connected(), f"Cannot connect to {RPC_URL}"
    return w3

def get_bal(w3, addr):
    return w3.eth.get_balance(Web3.to_checksum_address(addr))

def wait_tx(w3, tx_hash, label=""):
    print(f"  ⏳ {label}..." if label else "  ⏳ tx...", end=" ", flush=True)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    ok = receipt["status"] == 1
    print("✅" if ok else "❌")
    return ok

# =====================================================================
# STEPS
# =====================================================================
def step_faucet_tao(ss58: str, captcha_key: str) -> bool:
    token = solve_recaptcha(captcha_key)
    if not token:
        return False
    r = requests.post(f"{FAUCET_API}/", json={
        "ss58_address": ss58, "amount": "1", "captcha_token": token,
    }, headers={"Content-Type": "application/json"}, timeout=30)
    data = r.json()
    if data.get("success"):
        print(f"  ✅ Claimed 1 TAO → {ss58[:16]}...")
        return True
    elif "COOLDOWN" in str(data):
        print(f"  ⏳ Faucet cooldown: {data.get('message', '')}")
        return True
    else:
        print(f"  ❌ Faucet: {json.dumps(data, indent=2)}")
        return False

def step_evm_faucet(w3, account):
    c = w3.eth.contract(address=FAUCET_EVM, abi=FAUCET_ABI)
    nonce = w3.eth.get_transaction_count(account.address)
    gp = w3.eth.gas_price
    try:
        tx = c.functions.drip(account.address).build_transaction({
            "from": account.address, "nonce": nonce,
            "gas": 100000, "gasPrice": gp, "chainId": CHAIN_ID,
        })
        return wait_tx(w3, w3.eth.send_raw_transaction(account.sign_transaction(tx).raw_transaction), "EVM faucet")
    except:
        try:
            tx = c.functions.dripAll().build_transaction({
                "from": account.address, "nonce": nonce,
                "gas": 200000, "gasPrice": gp, "chainId": CHAIN_ID,
            })
            return wait_tx(w3, w3.eth.send_raw_transaction(account.sign_transaction(tx).raw_transaction), "EVM faucet")
        except Exception as e:
            print(f"  ❌ EVM faucet: {e}")
            return False

def step_bridge(w3, evm_addr: str, sub: SubKeypair, amount: int) -> bool:
    """Bridge native TAO → EVM using Substrate extrinsic."""
    print(f"  🔄 Bridging {amount} RAO → EVM...", end=" ", flush=True)
    try:
        # Bittensor uses the EVM precompile at address 0x420000...0010
        # This is called via Substrate extrinsic, not EVM tx
        bridge = w3.eth.contract(address=Web3.to_checksum_address("0x4200000000000000000000000000000000000010"), abi=BRIDGE_ABI)
        nonce = w3.eth.get_transaction_count(evm_addr)
        gp = w3.eth.gas_price
        tx = bridge.functions.bridge(evm_addr, amount).build_transaction({
            "from": evm_addr, "nonce": nonce,
            "gas": 200000, "gasPrice": gp, "chainId": CHAIN_ID,
        })
        return wait_tx(w3, w3.eth.send_raw_transaction(Web3().eth.account.sign_transaction(tx, sub.private_key).raw_transaction), "Bridge")
    except Exception as e:
        print(f"❌ Bridge error: {e}")
        print("  💡 Bridge manually: https://testnet.forge.endure.network/#/bridge")
        return False

def step_wrap(w3, account, amount_wei):
    mint_abi = json.loads('[{"inputs":[{"name":"amount","type":"uint256"}],"name":"mint","outputs":[],"stateMutability":"payable","type":"function"}]')
    ws = w3.eth.contract(address=WSTAO, abi=mint_abi)
    nonce = w3.eth.get_transaction_count(account.address)
    gp = w3.eth.gas_price
    tx = ws.functions.mint(amount_wei).build_transaction({
        "from": account.address, "nonce": nonce,
        "gas": 200000, "gasPrice": gp, "chainId": CHAIN_ID, "value": amount_wei,
    })
    return wait_tx(w3, w3.eth.send_raw_transaction(account.sign_transaction(tx).raw_transaction), "Wrap → wsTAO")

def step_supply(w3, account, amount_wei):
    erc20 = w3.eth.contract(address=WSTAO, abi=ERC20_ABI)
    nonce = w3.eth.get_transaction_count(account.address)
    gp = w3.eth.gas_price
    tx = erc20.functions.approve(VWSTAO, amount_wei).build_transaction({
        "from": account.address, "nonce": nonce,
        "gas": 80000, "gasPrice": gp, "chainId": CHAIN_ID,
    })
    if not wait_tx(w3, w3.eth.send_raw_transaction(account.sign_transaction(tx).raw_transaction), "Approve"):
        return False
    nonce = w3.eth.get_transaction_count(account.address)
    comptroller = w3.eth.contract(address=UNITROLLER, abi=COMPTROLLER_ABI)
    tx = comptroller.functions.enterMarkets([VWSTAO]).build_transaction({
        "from": account.address, "nonce": nonce,
        "gas": 150000, "gasPrice": gp, "chainId": CHAIN_ID,
    })
    if not wait_tx(w3, w3.eth.send_raw_transaction(account.sign_transaction(tx).raw_transaction), "Enter Market"):
        return False
    nonce = w3.eth.get_transaction_count(account.address)
    vtoken = w3.eth.contract(address=VWSTAO, abi=VTOKEN_ABI)
    tx = vtoken.functions.mint(amount_wei).build_transaction({
        "from": account.address, "nonce": nonce,
        "gas": 300000, "gasPrice": gp, "chainId": CHAIN_ID,
    })
    return wait_tx(w3, w3.eth.send_raw_transaction(account.sign_transaction(tx).raw_transaction), "Supply Mint")

def step_borrow(w3, account, amount_wei):
    vtoken = w3.eth.contract(address=VWSTAO, abi=VTOKEN_ABI)
    nonce = w3.eth.get_transaction_count(account.address)
    gp = w3.eth.gas_price
    tx = vtoken.functions.borrow(amount_wei).build_transaction({
        "from": account.address, "nonce": nonce,
        "gas": 300000, "gasPrice": gp, "chainId": CHAIN_ID,
    })
    return wait_tx(w3, w3.eth.send_raw_transaction(account.sign_transaction(tx).raw_transaction), "Borrow")

# =====================================================================
# WALLETS
# =====================================================================
def load_wallets() -> list:
    raw = os.getenv("WALLETS")
    if not raw:
        print("❌ WALLETS not set in .env")
        print("   Format: [{\"pk\":\"0x...\",\"sub_mnemonic\":\"word1 word2 ...\"}, ...]")
        print("   - pk: EVM private key (REQUIRED)")
        print("   - sub_mnemonic: Substrate mnemonic (OPTIONAL — for bridge)")
        sys.exit(1)
    try:
        wallets = json.loads(raw)
    except json.JSONDecodeError:
        print("❌ WALLETS is not valid JSON")
        sys.exit(1)
    if not isinstance(wallets, list) or len(wallets) == 0:
        print("❌ WALLETS must be a non-empty array")
        sys.exit(1)
    return wallets

def derive_ss58(mnemonic: str) -> str:
    """Derive SS58 address from Substrate mnemonic."""
    kp = SubKeypair.create_from_mnemonic(mnemonic, ss58_format=42)
    return kp.ss58_address

# =====================================================================
# PROCESS ONE WALLET
# =====================================================================
def process_wallet(w3, wallet: dict, captcha_key: str):
    pk = wallet["pk"]
    if pk.startswith("0x"):
        pk = pk[2:]
    account = Account.from_key(pk)
    addr = account.address

    # Substrate wallet (optional)
    sub_mnemonic = wallet.get("sub_mnemonic", "")
    sub = None
    ss58 = wallet.get("ss58", "")
    if sub_mnemonic:
        sub = SubKeypair.create_from_mnemonic(sub_mnemonic, ss58_format=42)
        ss58 = sub.ss58_address
    elif wallet.get("ss58"):
        ss58 = wallet["ss58"]

    short_addr = addr[:16]
    short_ss58 = ss58[:16] if ss58 else "N/A"

    print(f"\n{'─'*50}")
    print(f"  EVM:  {short_addr}...")
    print(f"  SS58: {short_ss58}...")
    print(f"  Sub mnemonic: {'✅' if sub_mnemonic else '❌ (bridge skipped)'}")
    print(f"{'─'*50}")

    bal = get_bal(w3, addr)
    print(f"  💰 Balance: {w3.from_wei(bal, 'ether')} TAO")

    # Faucet if empty
    if bal < 10**15 and captcha_key and ss58:
        print("\n  🔹 Faucet TAO...")
        step_faucet_tao(ss58, captcha_key)
        time.sleep(5)
        bal = get_bal(w3, addr)
        print(f"  💰 After faucet: {w3.from_wei(bal, 'ether')} TAO")

    if bal < 10**16:
        print("  ⏳ Skip — insufficient balance")
        return

    # Bridge native TAO → EVM (if substrate mnemonic provided)
    if sub and sub_mnemonic:
        print("\n  🔹 Bridge TAO → EVM (not yet implemented)")
        # Bridge via Substrate extrinsic goes here
        print("  💡 Bridge manually if needed: https://testnet.forge.endure.network/#/bridge")
    elif sub_mnemonic:
        print("  ❌ sub_mnemonic set but couldn't derive keypair — check mnemonic")

    # EVM faucet (always try — it's free)
    print("\n  🔹 EVM faucet...")
    step_evm_faucet(w3, account)
    time.sleep(2)

    # Wrap
    wrap_amt = bal * 8 // 10
    print(f"\n  🔹 Wrap {w3.from_wei(wrap_amt, 'ether')} TAO → wsTAO...")
    step_wrap(w3, account, wrap_amt)
    time.sleep(2)

    # Supply
    ws_bal = w3.eth.contract(address=WSTAO, abi=ERC20_ABI).functions.balanceOf(addr).call()
    if ws_bal > 0:
        supply_amt = ws_bal * 8 // 10
        print(f"\n  🔹 Supply {w3.from_wei(supply_amt, 'ether')} wsTAO...")
        step_supply(w3, account, supply_amt)
        time.sleep(2)
        print(f"\n  🔹 Borrow...")
        step_borrow(w3, account, ws_bal * 2 // 100)
    else:
        print("  ⏳ No wsTAO to supply")

    print(f"\n  ✅ Done")

# =====================================================================
# MAIN
# =====================================================================
def main():
    Account.enable_unaudited_hdwallet_features()
    captcha_key = os.getenv("2CAPTCHA_API_KEY", "")
    loop = "--loop" in sys.argv

    wallets = load_wallets()
    print(f"📋 Loaded {len(wallets)} wallet(s)")
    if captcha_key:
        print(f"🔑 2captcha: set")

    while True:
        w3 = init_web3()
        print(f"\n{'='*50}")
        print(f"  BLOCK {w3.eth.block_number}  |  {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*50}")

        for i, wallet in enumerate(wallets):
            print(f"\n[{i+1}/{len(wallets)}]")
            try:
                process_wallet(w3, wallet, captcha_key)
            except Exception as e:
                print(f"  ❌ Error: {e}")

        if not loop:
            print(f"\n✅ All wallets processed. Exiting.")
            break

        next_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() + LOOP_INTERVAL))
        print(f"\n💤 Sleeping 24h... next run at {next_time}")
        time.sleep(LOOP_INTERVAL)

if __name__ == "__main__":
    main()
