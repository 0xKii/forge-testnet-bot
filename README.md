# Forge Testnet Bot

Auto bot for [Forge Lending](https://testnet.forge.endure.network) on Bittensor EVM Testnet.

## Setup

```bash
git clone https://github.com/0xKii/forge-testnet-bot.git
cd forge-testnet-bot
pip install -r requirements.txt
cp .env.example .env
```

**Edit `.env`** — isi API key 2captcha sama wallet kamu:

```env
2CAPTCHA_API_KEY=your_2captcha_key_here
WALLETS=[{"pk":"0xPRIVATE_KEY","ss58":"5SS58_ADDRESS"}]
```

Untuk multi-account, tinggal tambahin array:
```env
WALLETS=[{"pk":"0xabc...","ss58":"5abc..."},{"pk":"0xdef...","ss58":"5def..."}]
```

## Usage

```bash
# Jalanin semua wallet sekali
python forge_bot.py

# Loop 24 jam
python forge_bot.py --loop
```

Bot akan otomatis untuk tiap wallet:
1. Claim TAO dari faucet (kalo balance 0)
2. Claim EVM faucet
3. Wrap TAO → wsTAO
4. Supply wsTAO ke Forge
5. Borrow

## Network

| | |
|---|---|
| Chain | Bittensor EVM Testnet |
| Chain ID | 945 |
| RPC | `https://test.chain.opentensor.ai` |
| Explorer | https://evm-testscan.dev.opentensor.ai |

## Disclaimer

For educational/testnet purposes only. Use at your own risk.
