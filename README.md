# Forge Testnet Bot

Full automation bot for [Forge Lending](https://testnet.forge.endure.network) on Bittensor EVM Testnet.

## Features

- ✅ **Wallet generation** — EVM + Substrate (SS58) wallet pair
- ✅ **Captcha solving** — reCAPTCHA v2 via 2captcha API
- ✅ **Faucet claim** — TAO from taoswap.org testnet faucet
- ✅ **EVM faucet** — Drip from Forge elementary-capped faucet
- ✅ **Wrap TAO → wsTAO** — Mint wrapped TAO
- ✅ **Supply wsTAO** — Approve → Enter Market → Mint vWsTAO
- ✅ **Borrow** — Borrow against supplied collateral

## Prerequisites

```bash
# Python 3.10+
pip install -r requirements.txt
```

## Usage

```bash
# Full auto (generate wallet + faucet + all steps)
python forge_bot.py --2captcha YOUR_2CAPTCHA_KEY

# Use existing wallet
python forge_bot.py --key EVM_PRIVATE_KEY --2captcha YOUR_2CAPTCHA_KEY

# EVM steps only (if already funded)
python forge_bot.py --key EVM_PRIVATE_KEY --auto
```

### Without 2captcha

If you don't have a 2captcha API key:

1. Get TAO from [taoswap.org testnet faucet](https://taoswap.org/testnet-faucet)
2. Bridge to EVM via Forge UI
3. Run EVM steps:

```bash
python forge_bot.py --key YOUR_EVM_PK --auto
```

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

## Disclaimer

For educational/testnet purposes only.
