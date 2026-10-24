# base-tx-decoder

x402-powered transaction decoder service for the Base blockchain.

## Endpoints

- `GET /health` — free health check
- `GET /decode?tx=0x...` — decode a Base transaction (0.002 USDC/call)

## Payment

Pay 0.002 USDC on Base (chain ID 8453) to `0x65aa59025C4AcD8CD7ba2051ecb9152abaE4fcC6`.
After payment, retry with `X-Payment-Tx: 0x...` header.

## License

MIT
