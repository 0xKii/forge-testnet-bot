#!/usr/bin/env python3
"""
Forge Testnet Automation Bot — 24/7 loop, multi-account, .env config
====================================================================
"""

import os, sys, json, time, re, argparse, logging
from typing import List, Optional, Tuple
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv

import requests
from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3
from substrateinterface import Keypair as SubKeypair

load_dotenv()

# ── Logging ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("forge")

# ── Consts ───────────────────────────────────────────────────
CHAIN_ID = 945
RPC_URL = "https://test.chain.opentensor.ai"
EXPLORER = "https://evm-testscan.dev.opentensor.ai"
SS58_PREFIX = 42

# Contract addresses (Bittensor EVM Testnet)
WTAO        = Web3.to_checksum_address("0x757bbFffe6f08FEbBE19638833FfADaa7B369C25")
WSTAO       = Web3.to_checksum_address("0xcff46eb93307ca7E24A7cE2A1Eb0F485A27D461a")
UNITROLLER  = Web3.to_checksum_address("0x999C6a7ee03aE0C0a18503C2ECA0C8d5a9f69f31")
VWSTAO      = Web3.to_checksum_address("0x782E5a6Dc16901ec13D4D1e450A8270F4e6E75cf")
FAUCET_EVM  = Web3.to_checksum_address("0x35c23b26B3A6bF06a5ECdD7420e800dB7c7866Fe")
FAUCET_API  = "https://api.taoswap.org/testnet-faucet"
CAPTCHA_SITEKEY = "6Ld0ZokrAAAAAAeIFmZpOZJ1dII3zY0Jkl6kUTdR"
CAPTCHA_PAGE   = "https://taoswap.org/testnet-faucet"

BASE_DIR = Path(__file__).parent.resolve()
WALLETS_FILE = BASE_DIR / "wallets.json"
CAPTCHA_KEY = os.getenv("2CAPTCHA_API_KEY", "")
LOOP_INTERVAL = int(os.getenv("LOOP_INTERVAL", "3600"))         # 1 jam
FAUCET_COOLDOWN = int(os.getenv("FAUCET_COOLDOWN", "86400"))    # 24 jam
MIN_BALANCE = 10 ** 16  # 0.01 TAO auto-trigger threshold

# ── ABIs ─────────────────────────────────────────────────────
ERC20_ABI = json.loads("""
[{"constant":false,"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"},
{"constant":true,"inputs":[{"name":"owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]
""")
FAUCET_ABI = json.loads("""
[{"inputs":[{"name":"recipient","type":"address"}],"name":"drip","outputs":[{"name":"","type":"uint256"}],"stateMutability":"nonpayable","type":"function"},
{"inputs":[],"name":"dripAll","outputs":[],"stateMutability":"nonpayable","type":"function"}]
""")
COMPTROLLER_ABI = json.loads("""
[{"constant":false,"inputs":[{"name":"vTokens","type":"address[]"}],"name":"enterMarkets","outputs":[{"name":"","type":"uint256[]"}],"stateMutability":"nonpayable","type":"function"}]
""")
MINT_ABI = json.loads('[{"inputs":[{"name":"amount","type":"uint256"}],"name":"mint","outputs":[],"stateMutability":"payable","type":"function"}]')
VTOKEN_ABI = json.loads("""
[{"constant":false,"inputs":[{"name":"amount","type":"uint256"}],"name":"mint","outputs":[{"name":"","type":"uint256"}],"stateMutability":"nonpayable","type":"function"},
{"constant":false,"inputs":[{"name":"borrowAmount","type":"uint256"}],"name":"borrow","outputs":[{"name":"","type":"uint256"}],"stateMutability":"nonpayable","type":"function"},
{"constant":true,"inputs":[{"name":"owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
{"constant":true,"inputs":[],"name":"exchangeRateStored","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]
""")
# ── Helpers ──────────────────────────────────────────────────
def w3():
    return Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 60}))

def bal_eth(w3c, addr):
    return w3c.eth.get_balance(Web3.to_checksum_address(addr))

def send_tx(w3c, acct, tx, label="tx"):
    signed = acct.sign_transaction(tx)
    tx_hash = w3c.eth.send_raw_transaction(signed.raw_transaction)
    log.info(f"  ⏳ {label} {str(tx_hash)[:20]}...")
    receipt = w3c.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    ok = receipt["status"] == 1
    log.info(f"  {'✅' if ok else '❌'} {label}")
    return {"success": ok, "tx": tx_hash.hex(), "receipt": receipt}


# ── Wallet Mgmt ──────────────────────────────────────────────
def load_or_create_wallets(count: int = 3) -> List[dict]:
    """Load wallets.json or create fresh ones."""
    Account.enable_unaudited_hdwallet_features()
    if WALLETS_FILE.exists():
        with open(WALLETS_FILE) as f:
            wallets = json.load(f)
        log.info(f"📂 Loaded {len(wallets)} wallet(s) from {WALLETS_FILE.name}")
        return wallets

    wallets = []
    for i in range(count):
        evm = Account.create()
        sub = SubKeypair.create_from_mnemonic(
            SubKeypair.generate_mnemonic(), ss58_format=SS58_PREFIX,
        )
        wallets.append({
            "evm_pk": evm.key.hex(),
            "evm_address": evm.address,
            "sub_mnemonic": sub.mnemonic,
            "ss58_address": sub.ss58_address,
            "last_faucet": 0,
            "created": datetime.utcnow().isoformat(),
        })
    save_wallets(wallets)
    log.info(f"🆕 Generated {len(wallets)} fresh wallet(s)")
    for w in wallets:
        log.info(f"   EVM: {w['evm_address']}  SS58: {w['ss58_address']}")
    return wallets

def save_wallets(wallets):
    # strip evm_pk from display save
    to_save = []
    for w in wallets:
        entry = dict(w)
        if "evm_pk" in entry:
            entry["evm_pk_hint"] = entry["evm_pk"][:8] + "..."
        to_save.append(entry)
    with open(WALLETS_FILE, "w") as f:
        json.dump(wallets, f, indent=2)

def get_account(w: dict) -> LocalAccount:
    return Account.from_key(w["evm_pk"])

def get_sub(w: dict) -> SubKeypair:
    return SubKeypair.create_from_mnemonic(w["sub_mnemonic"], ss58_format=SS58_PREFIX)


# ── 2captcha ────────────────────────────────────────────────
def solve_captcha(timeout=180) -> Optional[str]:
    if not CAPTCHA_KEY:
        log.warning("  ⚠️  2CAPTCHA_API_KEY not set")
        return None
    r = requests.post("https://2captcha.com/in.php", data={
        "key": CAPTCHA_KEY, "method": "userrecaptcha",
        "googlekey": CAPTCHA_SITEKEY, "pageurl": CAPTCHA_PAGE, "json": 1,
    }, timeout=30).json()
    rid = r.get("request")
    if r.get("status") != 1 or not rid:
        log.warning(f"  ⚠️  Captcha submit failed: {r}")
        return None

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(5)
        r = requests.get("https://2captcha.com/res.php", params={
            "key": CAPTCHA_KEY, "action": "get", "id": rid, "json": 1,
        }, timeout=10).json()
        if r.get("status") == 1:
            return r["request"]
    log.warning("  ⚠️  Captcha timeout")
    return None


# ── Faucet ───────────────────────────────────────────────────
def claim_tao_faucet(ss58: str, token: str) -> dict:
    r = requests.post(FAUCET_API + "/", json={
        "ss58_address": ss58, "amount": "1", "captcha_token": token,
    }, headers={"Content-Type": "application/json", "Referer": CAPTCHA_PAGE}, timeout=30)
    return {"code": r.status_code, "body": r.text[:300]}


def claim_evm_faucet(w3c, acct):
    c = w3c.eth.contract(address=FAUCET_EVM, abi=FAUCET_ABI)
    nonce = w3c.eth.get_transaction_count(acct.address)
    gp = w3c.eth.gas_price
    try:
        tx = c.functions.drip(acct.address).build_transaction({
            "from": acct.address, "nonce": nonce,
            "gas": 100000, "gasPrice": gp, "chainId": CHAIN_ID,
        })
        return send_tx(w3c, acct, tx, "EVM faucet drip")
    except Exception as e:
        log.warning(f"  drip failed: {e}, trying dripAll…")
        try:
            tx = c.functions.dripAll().build_transaction({
                "from": acct.address, "nonce": nonce,
                "gas": 200000, "gasPrice": gp, "chainId": CHAIN_ID,
            })
            return send_tx(w3c, acct, tx, "EVM faucet dripAll")
        except Exception as e2:
            return {"success": False, "error": str(e2)}


# ── Core pipeline ────────────────────────────────────────────
def run_pipeline(w: dict, force_faucet=False) -> dict:
    """Full pipeline for one wallet. Returns summary dict."""
    w3c = w3()
    acct = get_account(w)
    sub = get_sub(w)
    addr = acct.address
    result = {"wallet": addr, "steps": {}}

    # 1. Balance check
    bal = bal_eth(w3c, addr)
    result["balance_before"] = str(bal)
    log.info(f"💰 {addr[:12]} balance: {w3c.from_wei(bal, 'ether'):.4f} TAO")

    # 2. Faucet if low
    if (bal < MIN_BALANCE or force_faucet) and CAPTCHA_KEY:
        last = w.get("last_faucet", 0)
        if time.time() - last > FAUCET_COOLDOWN:
            log.info(f"🪙  Faucet claim for SS58 {sub.ss58_address[:12]}...")
            token = solve_captcha()
            if token:
                resp = claim_tao_faucet(sub.ss58_address, token)
                result["faucet"] = resp
                if resp["code"] == 200:
                    w["last_faucet"] = int(time.time())
                    log.info(f"   ✅ Faucet OK: {resp['body'][:80]}")
                    # After faucet, need to wait for bridge
                    log.info("   ⏳ Bridge native TAO → EVM manually via Forge UI")
                elif "FAUCET_COOLDOWN" in resp.get("body", ""):
                    log.warning(f"   ⏸️  Faucet daily limit")
                elif "VALIDATION_ERROR" in resp.get("body", ""):
                    log.warning(f"   ⚠️  Validation error (maybe need amount)")
            else:
                result["faucet"] = {"error": "captcha_failed"}
        else:
            cooldown_left = FAUCET_COOLDOWN - (time.time() - last)
            log.info(f"   ⏸️  Faucet cooldown {cooldown_left:.0f}s remaining")

    # Recheck balance
    bal = bal_eth(w3c, addr)
    result["balance"] = str(bal)
    if bal < 10 ** 15:
        log.warning(f"   ⏸️  Balance too low, skipping EVM steps")
        return result

    # 3. EVM faucet
    log.info(f"🔹 EVM faucet…")
    result["evm_faucet"] = claim_evm_faucet(w3c, acct)
    time.sleep(2)

    # 4. Wrap TAO → wsTAO
    wrap_amt = bal * 8 // 10
    if wrap_amt > 0:
        log.info(f"🔹 Wrap {w3c.from_wei(wrap_amt, 'ether'):.4f} TAO → wsTAO…")
        ws = w3c.eth.contract(address=WSTAO, abi=MINT_ABI)
        nonce = w3c.eth.get_transaction_count(addr)
        gp = w3c.eth.gas_price
        tx = ws.functions.mint(wrap_amt).build_transaction({
            "from": addr, "nonce": nonce,
            "gas": 200000, "gasPrice": gp, "chainId": CHAIN_ID, "value": wrap_amt,
        })
        result["wrap"] = send_tx(w3c, acct, tx, "Wrap TAO→wsTAO")
        time.sleep(2)

    # 5. Supply wsTAO
    ws_bal = w3c.eth.contract(address=WSTAO, abi=ERC20_ABI).functions.balanceOf(addr).call()
    if ws_bal > 0:
        supply_amt = ws_bal * 8 // 10
        log.info(f"🔹 Supply {w3c.from_wei(supply_amt, 'ether'):.4f} wsTAO…")

        # Approve
        erc20 = w3c.eth.contract(address=WSTAO, abi=ERC20_ABI)
        nonce = w3c.eth.get_transaction_count(addr)
        gp = w3c.eth.gas_price
        tx = erc20.functions.approve(VWSTAO, supply_amt).build_transaction({
            "from": addr, "nonce": nonce,
            "gas": 80000, "gasPrice": gp, "chainId": CHAIN_ID,
        })
        result["approve"] = send_tx(w3c, acct, tx, "Approve wsTAO")
        time.sleep(1)

        # Enter Market
        comp = w3c.eth.contract(address=UNITROLLER, abi=COMPTROLLER_ABI)
        nonce = w3c.eth.get_transaction_count(addr)
        tx = comp.functions.enterMarkets([VWSTAO]).build_transaction({
            "from": addr, "nonce": nonce,
            "gas": 150000, "gasPrice": gp, "chainId": CHAIN_ID,
        })
        result["enter_market"] = send_tx(w3c, acct, tx, "Enter Market")
        time.sleep(1)

        # Mint
        vtoken = w3c.eth.contract(address=VWSTAO, abi=VTOKEN_ABI)
        nonce = w3c.eth.get_transaction_count(addr)
        tx = vtoken.functions.mint(supply_amt).build_transaction({
            "from": addr, "nonce": nonce,
            "gas": 300000, "gasPrice": gp, "chainId": CHAIN_ID,
        })
        result["supply"] = send_tx(w3c, acct, tx, "Supply Mint")
        time.sleep(2)

        # 6. Borrow
        borrow_amt = ws_bal * 2 // 100
        log.info(f"🔹 Borrow {w3c.from_wei(borrow_amt, 'ether'):.4f}…")
        nonce = w3c.eth.get_transaction_count(addr)
        tx = vtoken.functions.borrow(borrow_amt).build_transaction({
            "from": addr, "nonce": nonce,
            "gas": 300000, "gasPrice": gp, "chainId": CHAIN_ID,
        })
        result["borrow"] = send_tx(w3c, acct, tx, "Borrow")

    return result


# ── Main loop ────────────────────────────────────────────────
def main_loop():
    log.info("=" * 56)
    log.info("  FORGE TESTNET BOT — 24/7 AUTO")
    log.info(f"  Captcha: {'✅' if CAPTCHA_KEY else '❌'}")
    log.info(f"  Loop interval: {LOOP_INTERVAL}s")
    log.info(f"  Faucet cooldown: {FAUCET_COOLDOWN}s")
    log.info("=" * 56)

    wallets = load_or_create_wallets(int(os.getenv("WALLET_COUNT", "3")))
    iteration = 0

    while True:
        iteration += 1
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        log.info(f"\n{'─'*56}")
        log.info(f"  🔄 Iteration #{iteration}  —  {now}")
        log.info(f"{'─'*56}")

        for i, w in enumerate(wallets):
            log.info(f"\n{'─'*40}")
            log.info(f"  Wallet #{i+1} / {len(wallets)}")
            log.info(f"  EVM: {w['evm_address']}")
            log.info(f"  SS58: {w['ss58_address']}")
            log.info(f"{'─'*40}")

            try:
                result = run_pipeline(w)
                # Log key results
                for step, r in result.items():
                    if isinstance(r, dict) and "success" in r:
                        icon = "✅" if r["success"] else "❌"
                        log.info(f"  {icon} {step}")
            except Exception as e:
                log.error(f"  ❌ Pipeline error: {e}", exc_info=True)

            save_wallets(wallets)
            log.info(f"  💾 wallets.json saved")
            # Small pause between wallets
            time.sleep(5)

        # Generate new wallets if needed
        if iteration > 0 and iteration % 12 == 0:  # roughly every 12 loops
            for _ in range(2):
                evm = Account.create()
                sub = SubKeypair.create_from_mnemonic(
                    SubKeypair.generate_mnemonic(), ss58_format=SS58_PREFIX,
                )
                wallets.append({
                    "evm_pk": evm.key.hex(),
                    "evm_address": evm.address,
                    "sub_mnemonic": sub.mnemonic,
                    "ss58_address": sub.ss58_address,
                    "last_faucet": 0,
                    "created": datetime.utcnow().isoformat(),
                })
                log.info(f"🆕 New wallet: {evm.address} / {sub.ss58_address}")
            save_wallets(wallets)

        next_run = datetime.utcnow() + timedelta(seconds=LOOP_INTERVAL)
        log.info(f"\n💤 Sleeping {LOOP_INTERVAL}s — next run ~{next_run.strftime('%H:%M:%S')} UTC")
        time.sleep(LOOP_INTERVAL)


# ── CLI ──────────────────────────────────────────────────────
if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true", help="Single run (no loop)")
    p.add_argument("--wallet", help="Process a specific wallet index (0-based)")
    args = p.parse_args()

    if args.once:
        wallets = load_or_create_wallets()
        idx = int(args.wallet) if args.wallet else 0
        if idx < len(wallets):
            run_pipeline(wallets[idx], force_faucet=True)
            save_wallets(wallets)
        else:
            log.error(f"Wallet index {idx} out of range (0..{len(wallets)-1})")
    else:
        main_loop()
