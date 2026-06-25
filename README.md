# Forge Testnet Bot

24/7 automation bot for [Forge Lending](https://testnet.forge.endure.network) on Bittensor EVM Testnet.

## Features

- ✅ **Multi-account** — manages multiple wallets automatically
- ✅ **Wallet generation** — EVM + Substrate (SS58) pair each
- ✅ **Captcha solving** — reCAPTCHA v2 via 2captcha
- ✅ **Faucet claim** — TAO from taoswap.org
- ✅ **EVM faucet** — Drip from Forge faucet contract
- ✅ **Wrap TAO → wsTAO** — Mint wrapped TAO
- ✅ **Supply wsTAO** — Approve → Enter Market → Mint vWsTAO
- ✅ **Borrow** — Borrow against supplied collateral
- ✅ **24/7 loop** — Runs forever, generates new wallets, tracks cooldowns

## Quick Start

```bash
# 1. Install
git clone https://github.com/0xKii/forge-testnet-bot.git
cd forge-testnet-bot
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env — add your 2captcha key

# 3. Run
python forge_bot.py
```

## Configuration (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `2CAPTCHA_API_KEY` | — | **Required.** Your 2captcha API key |
| `LOOP_INTERVAL` | `3600` | Seconds between iterations (1h) |
| `FAUCET_COOLDOWN` | `86400` | Cooldown per wallet between faucet claims (24h) |
| `WALLET_COUNT` | `3` | Wallets to generate at first run |

## Commands

```bash
# Normal 24/7 loop mode (auto-generates wallets)
python forge_bot.py

# Single run for specific wallet
python forge_bot.py --once --wallet 0
```

## How it works

1. Loads wallets from `wallets.json` (or generates fresh ones)
2. For each wallet:
   - If balance < 0.01 TAO → claim faucet (2captcha + taoswap API)
   - Claim EVM faucet (drip)
   - Wrap 80% TAO → wsTAO
   - Supply 80% wsTAO to Forge
   - Borrow 2% of supplied amount
3. Every 12 iterations, generates 2 new wallets
4. Sleeps LOOP_INTERVAL seconds, then repeats

## Network

| Parameter | Value |
|-----------|-------|
| Chain | Bittensor EVM Testnet |
| Chain ID | 945 |
| RPC | https://test.chain.opentensor.ai |
| Explorer | https://evm-testscan.dev.opentensor.ai |

## Contract Addresses (testnet)

| Contract | Address |
|----------|---------|
| Unitroller | `0x999C6a7ee03aE0C0a18503C2ECA0C8d5a9f69f31` |
| wsTAO | `0xcff46eb93307ca7E24A7cE2A1Eb0F485A27D461a` |
| vWsTAO | `0x782E5a6Dc16901ec13D4D1e450A8270F4e6E75cf` |
| Faucet | `0x35c23b26B3A6bF06a5ECdD7420e800dB7c7866Fe` |

## Manual Bridge

After faucet claim, native TAO needs to be bridged to EVM:
- Go to [Forge Bridge](https://testnet.forge.endure.network/#/bridge)
- Or use `btcli wallet transfer` on testnet

## Disclaimer

For educational/testnet purposes only.
