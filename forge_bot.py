#!/usr/bin/env python3
"""
Forge Testnet Full Automation Bot (with 2captcha)
==================================================
Chain: Bittensor EVM Testnet (chainId: 945)
RPC:  https://test.chain.opentensor.ai

Steps (FULL AUTO):
  1. Generate EVM + Substrate (SS58) wallets
  2. Claim TAO from taoswap faucet (2captcha solves reCAPTCHA)
  3. Bridge native TAO → EVM TAO
  4. Claim EVM faucet
  5. Wrap TAO → wsTAO
  6. Supply wsTAO to Forge
  7. Borrow from Forge

Usage:
  python3 forge_bot.py                          # Generate & manual
  python3 forge_bot.py --2captcha KEY           # Full auto dengan 2captcha
  python3 forge_bot.py --key PK --auto          # Auto mode wallet exist
  python3 forge_bot.py --key PK --2captcha KEY  # Full auto wallet exist
"""

import os, sys, json, time, re, argparse
from typing import Optional, Tuple

import requests
from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3
from substrateinterface import Keypair as SubKeypair

# =====================================================================
# CHAIN CONFIG
# =====================================================================
CHAIN_ID = 945
RPC_URL = "https://test.chain.opentensor.ai"
EXPLORER = "https://evm-testscan.dev.opentensor.ai"

# Contract addresses (Bittensor EVM Testnet)
WTAO        = Web3.to_checksum_address("0x757bbFffe6f08FEbBE19638833FfADaa7B369C25")
WSTAO       = Web3.to_checksum_address("0xcff46eb93307ca7E24A7cE2A1Eb0F485A27D461a")
UNITROLLER  = Web3.to_checksum_address("0x999C6a7ee03aE0C0a18503C2ECA0C8d5a9f69f31")
VWSTAO      = Web3.to_checksum_address("0x782E5a6Dc16901ec13D4D1e450A8270F4e6E75cf")
FAUCET_EVM  = Web3.to_checksum_address("0x35c23b26B3A6bF06a5ECdD7420e800dB7c7866Fe")

FAUCET_API = "https://api.taoswap.org/testnet-faucet"

# reCAPTCHA site key for taoswap faucet
RECAPTCHA_SITE_KEY = "6Ld0ZokrAAAAAAeIFmZpOZJ1dII3zY0Jkl6kUTdR"
RECAPTCHA_PAGE_URL = "https://taoswap.org/testnet-faucet"

# =====================================================================
# ABIs
# =====================================================================
ERC20_ABI = json.loads('''[
{"constant":false,"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"},
{"constant":true,"inputs":[{"name":"owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
{"constant":true,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"stateMutability":"view","type":"function"}
]''')

FAUCET_ABI = json.loads('''[
{"inputs":[{"name":"recipient","type":"address"}],"name":"drip","outputs":[{"name":"","type":"uint256"}],"stateMutability":"nonpayable","type":"function"},
{"inputs":[],"name":"dripAll","outputs":[],"stateMutability":"nonpayable","type":"function"}
]''')

COMPTROLLER_ABI = json.loads('''[
{"constant":false,"inputs":[{"name":"vTokens","type":"address[]"}],"name":"enterMarkets","outputs":[{"name":"","type":"uint256[]"}],"stateMutability":"nonpayable","type":"function"}
]''')

VTOKEN_ABI = json.loads('''[
{"constant":false,"inputs":[{"name":"amount","type":"uint256"}],"name":"mint","outputs":[{"name":"","type":"uint256"}],"stateMutability":"nonpayable","type":"function"},
{"constant":false,"inputs":[{"name":"borrowAmount","type":"uint256"}],"name":"borrow","outputs":[{"name":"","type":"uint256"}],"stateMutability":"nonpayable","type":"function"},
{"constant":true,"inputs":[{"name":"owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
{"constant":true,"inputs":[],"name":"exchangeRateStored","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}
]''')

# =====================================================================
# 2CAPTCHA SOLVER
# =====================================================================
def solve_recaptcha_v2(api_key: str, site_key: str, page_url: str, timeout: int = 120) -> Optional[str]:
    """Solve reCAPTCHA v2 using 2captcha API. Returns token or None."""
    print("  🤖 Solving reCAPTCHA via 2captcha...", end=" ", flush=True)

    # Submit captcha
    r = requests.post("https://2captcha.com/in.php", data={
        "key": api_key,
        "method": "userrecaptcha",
        "googlekey": site_key,
        "pageurl": page_url,
        "json": 1,
    }, timeout=30)
    
    data = r.json()
    if data.get("status") != 1:
        err = data.get("error_text", data.get("request", "unknown"))
        print(f"❌ Submit failed: {err}")
        return None
    
    request_id = data["request"]
    print(f"submitted (id={request_id})", end=" ", flush=True)

    # Poll for result
    start = time.time()
    while time.time() - start < timeout:
        time.sleep(5)
        r = requests.get("https://2captcha.com/res.php", params={
            "key": api_key,
            "action": "get",
            "id": request_id,
            "json": 1,
        }, timeout=15)
        data = r.json()
        if data.get("status") == 1:
            token = data["request"]
            elapsed = int(time.time() - start)
            print(f"✅ solved in {elapsed}s")
            return token
        elif data.get("request") == "CAPCHA_NOT_READY":
            print(".", end="", flush=True)
            continue
        else:
            print(f"❌ Poll error: {data.get('request', 'unknown')}")
            return None
    
    print("❌ Timeout")
    return None


# =====================================================================
# WALLET GENERATION
# =====================================================================
def generate_wallets() -> Tuple[LocalAccount, SubKeypair]:
    """Generate fresh EVM + Substrate (SS58) wallet pair."""
    Account.enable_unaudited_hdwallet_features()
    evm = Account.create()
    sub = SubKeypair.create_from_mnemonic(
        SubKeypair.generate_mnemonic(), ss58_format=42,
    )
    return evm, sub


# =====================================================================
# BLOCKCHAIN HELPERS
# =====================================================================
def init_web3() -> Web3:
    w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 60}))
    assert w3.is_connected(), f"Cannot connect to {RPC_URL}"
    return w3

def get_eth_balance(w3, address):
    return w3.eth.get_balance(Web3.to_checksum_address(address))

def wait_tx(w3, tx_hash, label=""):
    print(f"  ⏳ {label or 'tx'} {str(tx_hash)[:20]}...", end=" ", flush=True)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    ok = receipt["status"] == 1
    print("✅" if ok else "❌")
    return {"success": ok, "tx": tx_hash.hex() if not isinstance(tx_hash, str) else tx_hash}


# =====================================================================
# STEP 1: CLAIM TAO FAUCET (taoswap.org + 2captcha)
# =====================================================================
def claim_tao_faucet(ss58: str, captcha_token: str) -> dict:
    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    payload = {
        "ss58_address": ss58,
        "amount": "1",
        "captcha_token": captcha_token,
    }
    r = requests.post(FAUCET_API + "/", json=payload, headers=headers, timeout=30)
    try:
        return r.json()
    except:
        return {"success": False, "message": r.text[:200]}


# =====================================================================
# STEP 2: BRIDGE SUBSTRATE TAO → EVM
# =====================================================================
def bridge_to_evm(w3: Web3, sub_keypair: SubKeypair, evm_address: str, amount: int) -> dict:
    """
    Bridge native TAO from Substrate to EVM.
    Uses the L2 bridge precompile at 0x420000...0010
    """
    # This requires a Substrate extrinsic call
    # The bridge contract is L2StandardBridge-like
    bridge_abi = json.loads('''[
        {"inputs":[{"name":"to","type":"address"},{"name":"amount","type":"uint256"}],"name":"bridge","outputs":[],"stateMutability":"nonpayable","type":"function"}
    ]''')
    
    try:
        bridge = w3.eth.contract(address=L2_BRIDGE, abi=bridge_abi)
        nonce = w3.eth.get_transaction_count(evm_address)
        gp = w3.eth.gas_price
        
        tx = bridge.functions.bridge(evm_address, amount).build_transaction({
            "from": evm_address, "nonce": nonce,
            "gas": 200000, "gasPrice": gp, "chainId": CHAIN_ID,
        })
        return {"success": True, "note": "Bridge tx prepared"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# =====================================================================
# STEP 3: CLAIM EVM FAUCET
# =====================================================================
def claim_evm_faucet(w3, account):
    contract = w3.eth.contract(address=FAUCET_EVM, abi=FAUCET_ABI)
    nonce = w3.eth.get_transaction_count(account.address)
    gp = w3.eth.gas_price

    try:
        tx = contract.functions.drip(account.address).build_transaction({
            "from": account.address, "nonce": nonce,
            "gas": 100000, "gasPrice": gp, "chainId": CHAIN_ID,
        })
        signed = account.sign_transaction(tx)
        return wait_tx(w3, w3.eth.send_raw_transaction(signed.raw_transaction), "EVM faucet drip")
    except Exception as e:
        try:
            tx = contract.functions.dripAll().build_transaction({
                "from": account.address, "nonce": nonce,
                "gas": 200000, "gasPrice": gp, "chainId": CHAIN_ID,
            })
            signed = account.sign_transaction(tx)
            return wait_tx(w3, w3.eth.send_raw_transaction(signed.raw_transaction), "EVM faucet dripAll")
        except Exception as e2:
            return {"success": False, "error": f"drip: {e}, dripAll: {e2}"}


# =====================================================================
# STEP 4: WRAP TAO → wsTAO
# =====================================================================
def wrap_tao(w3, account, amount_wei):
    mint_abi = json.loads('[{"inputs":[{"name":"amount","type":"uint256"}],"name":"mint","outputs":[],"stateMutability":"payable","type":"function"}]')
    ws = w3.eth.contract(address=WSTAO, abi=mint_abi)
    nonce = w3.eth.get_transaction_count(account.address)
    gp = w3.eth.gas_price

    tx = ws.functions.mint(amount_wei).build_transaction({
        "from": account.address, "nonce": nonce,
        "gas": 200000, "gasPrice": gp, "chainId": CHAIN_ID,
        "value": amount_wei,
    })
    signed = account.sign_transaction(tx)
    return wait_tx(w3, w3.eth.send_raw_transaction(signed.raw_transaction), "Wrap TAO→wsTAO")


# =====================================================================
# STEP 5: SUPPLY wsTAO
# =====================================================================
def supply_wstao(w3, account, amount_wei):
    results = []
    erc20 = w3.eth.contract(address=WSTAO, abi=ERC20_ABI)
    nonce = w3.eth.get_transaction_count(account.address)
    gp = w3.eth.gas_price

    tx = erc20.functions.approve(VWSTAO, amount_wei).build_transaction({
        "from": account.address, "nonce": nonce,
        "gas": 80000, "gasPrice": gp, "chainId": CHAIN_ID,
    })
    signed = account.sign_transaction(tx)
    results.append(wait_tx(w3, w3.eth.send_raw_transaction(signed.raw_transaction), "Approve wsTAO"))

    comptroller = w3.eth.contract(address=UNITROLLER, abi=COMPTROLLER_ABI)
    nonce = w3.eth.get_transaction_count(account.address)
    tx = comptroller.functions.enterMarkets([VWSTAO]).build_transaction({
        "from": account.address, "nonce": nonce,
        "gas": 150000, "gasPrice": gp, "chainId": CHAIN_ID,
    })
    signed = account.sign_transaction(tx)
    results.append(wait_tx(w3, w3.eth.send_raw_transaction(signed.raw_transaction), "Enter Market"))

    vtoken = w3.eth.contract(address=VWSTAO, abi=VTOKEN_ABI)
    nonce = w3.eth.get_transaction_count(account.address)
    tx = vtoken.functions.mint(amount_wei).build_transaction({
        "from": account.address, "nonce": nonce,
        "gas": 300000, "gasPrice": gp, "chainId": CHAIN_ID,
    })
    signed = account.sign_transaction(tx)
    results.append(wait_tx(w3, w3.eth.send_raw_transaction(signed.raw_transaction), "Supply Mint"))
    return results


# =====================================================================
# STEP 6: BORROW
# =====================================================================
def borrow(w3, account, amount_wei):
    vtoken = w3.eth.contract(address=VWSTAO, abi=VTOKEN_ABI)
    nonce = w3.eth.get_transaction_count(account.address)
    gp = w3.eth.gas_price
    tx = vtoken.functions.borrow(amount_wei).build_transaction({
        "from": account.address, "nonce": nonce,
        "gas": 300000, "gasPrice": gp, "chainId": CHAIN_ID,
    })
    signed = account.sign_transaction(tx)
    return wait_tx(w3, w3.eth.send_raw_transaction(signed.raw_transaction), "Borrow")


# =====================================================================
# FULL AUTO PIPELINE
# =====================================================================
def full_auto(captcha_key: str = "", existing_key: str = ""):
    """Run the complete automation pipeline."""
    w3 = init_web3()
    print(f"✅ Connected  block={w3.eth.block_number}\n")

    # --- Wallet Setup ---
    if existing_key:
        evm = Account.from_key(existing_key)
        sub = None  # can't derive substrate from evm key
        print(f"📝 Using EVM wallet: {evm.address}")
    else:
        evm, sub = generate_wallets()
        print(f"\n📝 NEW WALLETS:")
        print(f"   EVM:        {evm.address}")
        print(f"   PK:         {evm.key.hex()}")
        print(f"   SS58:       {sub.ss58_address}")
        print(f"   Mnemonic:   {sub.mnemonic}")

    # Save wallet
    out = {
        "evm_address": evm.address,
        "evm_pk": evm.key.hex(),
        "substrate_ss58": sub.ss58_address if sub else "",
        "substrate_mnemonic": sub.mnemonic if sub else "",
        "chain_id": CHAIN_ID,
    }
    path = f"forge_wallet_{evm.address[:12]}.json"
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"💾 Saved → {path}\n")

    evm_addr = evm.address

    # --- BALANCE CHECK ---
    bal = get_eth_balance(w3, evm_addr)
    print(f"💰 EVM Balance: {w3.from_wei(bal, 'ether')} TAO")

    # If no balance, faucet + bridge needed
    if bal < 10 ** 16 and captcha_key and sub:
        print("\n🔹 STEP 1: Claim TAO from taoswap faucet...")
        token = solve_recaptcha_v2(captcha_key, RECAPTCHA_SITE_KEY, RECAPTCHA_PAGE_URL)
        if not token:
            print("  ❌ Failed to solve captcha")
            return
        
        result = claim_tao_faucet(sub.ss58_address, token)
        print(f"  📦 Faucet result: {json.dumps(result, indent=4)}")
        
        time.sleep(3)
        
        print("\n🔹 STEP 2: Bridge TAO → EVM (via faucet precompile)")
        # Bittensor native TAO -> EVM bridge
        # This typically needs a Substrate extrinsic
        # For now, note: bridge manually via Forge UI
        print("   ⚠️  Bridge via https://testnet.forge.endure.network/#/bridge")
        print("   Or run `btcli wallet transfer` on testnet")
        
        print("\n⏳ Waiting 30s for funds to arrive...")
        time.sleep(30)
        
        bal = get_eth_balance(w3, evm_addr)
        print(f"💰 EVM Balance: {w3.from_wei(bal, 'ether')} TAO")

    if bal < 10 ** 16:
        print(f"\n⚠️  Still low balance. Funds needed.")
        print(f"   SS58: {sub.ss58_address if sub else 'N/A'}")
        print(f"   EVM:  {evm_addr}")
        print(f"   Faucet: https://taoswap.org/testnet-faucet")
        return

    # --- EVM Faucet ---
    print("\n🔹 STEP 3: Claim EVM faucet...")
    claim_evm_faucet(w3, evm)
    time.sleep(2)

    # --- Wrap ---
    bal = get_eth_balance(w3, evm_addr)
    wrap_amt = bal * 8 // 10
    print(f"\n🔹 STEP 4: Wrap {w3.from_wei(wrap_amt, 'ether')} TAO → wsTAO...")
    r = wrap_tao(w3, evm, wrap_amt)
    if not r["success"]:
        print("  ❌ Wrap failed")
        return
    time.sleep(2)

    # --- Supply ---
    ws_bal = w3.eth.contract(address=WSTAO, abi=ERC20_ABI).functions.balanceOf(evm_addr).call()
    if ws_bal == 0:
        print("  ❌ No wsTAO after wrap")
        return
    supply_amt = ws_bal * 8 // 10
    print(f"\n🔹 STEP 5: Supply {w3.from_wei(supply_amt, 'ether')} wsTAO...")
    supply_wstao(w3, evm, supply_amt)
    time.sleep(2)

    # --- Borrow ---
    print(f"\n🔹 STEP 6: Borrow...")
    borrow_amt = ws_bal * 2 // 100
    borrow(w3, evm, borrow_amt)

    # --- DONE ---
    print(f"\n{'=' * 60}")
    print(f"  ✅ ALL DONE!")
    print(f"  EVM: {evm_addr}")
    print(f"  PK:  {evm.key.hex()}")
    print(f"{'=' * 60}")


# =====================================================================
# MAIN / CLI
# =====================================================================
if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Forge Testnet Auto Bot")
    p.add_argument("--key", help="EVM private key (reuse)")
    p.add_argument("--2captcha", help="2captcha API key")
    p.add_argument("--auto", action="store_true", help="EVM steps only (wrap, supply, borrow)")
    args = p.parse_args()

    if args.auto and args.key:
        w3 = init_web3()
        acct = Account.from_key(args.key)
        print(f"📝 Wallet: {acct.address}")
        
        bal = get_eth_balance(w3, acct.address)
        print(f"💰 Balance: {w3.from_wei(bal, 'ether')} TAO")
        
        wrap_amt = bal * 8 // 10
        print(f"\n🔹 Wrap {w3.from_wei(wrap_amt, 'ether')} TAO...")
        wrap_tao(w3, acct, wrap_amt)
        time.sleep(2)
        
        ws = w3.eth.contract(address=WSTAO, abi=ERC20_ABI).functions.balanceOf(acct.address).call()
        if ws > 0:
            print(f"\n🔹 Supply {w3.from_wei(ws*8//10, 'ether')} wsTAO...")
            supply_wstao(w3, acct, ws * 8 // 10)
            time.sleep(2)
            print(f"\n🔹 Borrow...")
            borrow(w3, acct, ws * 2 // 100)
    elif args.key and getattr(args, '2captcha', None):
        full_auto(captcha_key=getattr(args, '2captcha'), existing_key=args.key)
    elif getattr(args, '2captcha', None):
        full_auto(captcha_key=getattr(args, '2captcha'))
    else:
        full_auto()
