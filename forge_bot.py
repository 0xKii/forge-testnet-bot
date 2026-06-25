#!/usr/bin/env python3
"""
Forge Testnet Automation Bot
=============================
Chain: Bittensor EVM Testnet (chainId: 945)
RPC:  https://test.chain.opentensor.ai

Steps:
  1. Claim TAO from taoswap faucet (2captcha solves reCAPTCHA)
  2. Claim EVM faucet
  3. Wrap TAO → wsTAO
  4. Supply wsTAO to Forge
  5. Borrow from Forge

Usage:
  python forge_bot.py              # Run all wallets once
  python forge_bot.py --loop       # Loop every 24 hours
"""

import os, sys, json, time, re
from typing import Optional
from dotenv import load_dotenv

import requests
from eth_account import Account
from web3 import Web3

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

# =====================================================================
# 2CAPTCHA
# =====================================================================
def solve_recaptcha(api_key: str) -> Optional[str]:
    print("  🤖 Solving reCAPTCHA...", end=" ", flush=True)
    r = requests.post("https://2captcha.com/in.php", data={
        "key": api_key, "method": "userrecaptcha",
        "googlekey": RECAPTCHA_SITE_KEY, "pageurl": RECAPTCHA_PAGE_URL,
        "json": 1,
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
            print(f"✅ in {(i+1)*5}s")
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
    print(f"  ⏳ {label}..." if label else f"  ⏳ tx...", end=" ", flush=True)
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
    r = requests.post(FAUCET_API + "/", json={
        "ss58_address": ss58, "amount": "1", "captcha_token": token,
    }, headers={"Content-Type": "application/json"}, timeout=30)
    data = r.json()
    if data.get("success"):
        print(f"  ✅ Claimed 1 TAO → {ss58[:16]}...")
        return True
    elif "COOLDOWN" in str(data):
        print(f"  ⏳ Faucet cooldown: {data.get('message', '')}")
        return True  # not an error, just wait
    else:
        print(f"  ❌ Faucet: {data}")
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
            return wait_tx(w3, w3.eth.send_raw_transaction(account.sign_transaction(tx).raw_transaction), "EVM faucet dripAll")
        except Exception as e:
            print(f"  ❌ EVM faucet: {e}")
            return False

def step_wrap(w3, account, amount_wei):
    mint_abi = json.loads('[{"inputs":[{"name":"amount","type":"uint256"}],"name":"mint","outputs":[],"stateMutability":"payable","type":"function"}]')
    ws = w3.eth.contract(address=WSTAO, abi=mint_abi)
    nonce = w3.eth.get_transaction_count(account.address)
    gp = w3.eth.gas_price
    tx = ws.functions.mint(amount_wei).build_transaction({
        "from": account.address, "nonce": nonce,
        "gas": 200000, "gasPrice": gp, "chainId": CHAIN_ID,
        "value": amount_wei,
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
    ok = wait_tx(w3, w3.eth.send_raw_transaction(account.sign_transaction(tx).raw_transaction), "Approve")
    if not ok: return False

    nonce = w3.eth.get_transaction_count(account.address)
    comptroller = w3.eth.contract(address=UNITROLLER, abi=COMPTROLLER_ABI)
    tx = comptroller.functions.enterMarkets([VWSTAO]).build_transaction({
        "from": account.address, "nonce": nonce,
        "gas": 150000, "gasPrice": gp, "chainId": CHAIN_ID,
    })
    ok = wait_tx(w3, w3.eth.send_raw_transaction(account.sign_transaction(tx).raw_transaction), "Enter Market")
    if not ok: return False

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
# WALLET
# =====================================================================
def load_wallets():
    """Read wallets from WALLETS env var (JSON array)."""
    raw = os.getenv("WALLETS")
    if not raw:
        print("❌ WALLETS not set in .env")
        print("   Format: [{\"pk\":\"0x...\",\"ss58\":\"5...\"}, ...]")
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

# =====================================================================
# PROCESS ONE WALLET
# =====================================================================
def process_wallet(w3, wallet: dict, captcha_key: str):
    pk = wallet["pk"]
    if pk.startswith("0x"):
        pk = pk[2:]
    account = Account.from_key(pk)
    ss58 = wallet.get("ss58", "")
    addr = account.address

    print(f"\n{'─'*50}")
    print(f"  Wallet: {addr[:16]}...")
    if ss58:
        print(f"  SS58:   {ss58[:16]}...")
    print(f"{'─'*50}")

    bal = get_bal(w3, addr)
    print(f"  💰 Balance: {w3.from_wei(bal, 'ether')} TAO")

    # Faucet if empty
    if bal < 10**15 and captcha_key and ss58:
        print("\n  🔹 Faucet TAO...")
        step_faucet_tao(ss58, captcha_key)
        time.sleep(5)
        print("  🔹 EVM faucet...")
        step_evm_faucet(w3, account)
        time.sleep(3)
        bal = get_bal(w3, addr)
        print(f"  💰 Balance: {w3.from_wei(bal, 'ether')} TAO")

    if bal < 10**16:
        print("  ⏳ Skip — insufficient balance")
        return

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

    print(f"\n  ✅ Done: {addr[:16]}...")

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
        print(f"🔑 2captcha: {'set' if captcha_key else 'not set'}")

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
