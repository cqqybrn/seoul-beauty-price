# Ubuntu ARM64 deployment

No remote server has been configured or verified by this repository. Do not enable the timer until
source parsers, real site domain, provider tariffs, golden accuracy, and alerts are accepted.

1. Provision Ubuntu ARM64, 2 CPU / 12 GB. Install Python 3.12, uv, Node >=22, Caddy and the official
   ARM64 Litestream release. Verify release hashes before installing binaries.
2. Place repo at `/opt/kbeauty-price`, create unprivileged `kbeauty` user, grant ownership of data,
   dictionary, and Astro cache directories. Run `uv sync --frozen` and `cd web && npm ci && npm run build`.
3. Store real configuration in `/etc/kbeauty-price.env`, mode 600; set `PIPELINE_SITE_URL`,
   `SITE_DOMAIN`, API keys, exact model IDs and verified provider token prices. Never expose env to web.
4. Copy Caddyfile and systemd units; validate with `caddy validate` and `systemd-analyze verify`.
   Allow 80/443 in BOTH Oracle security lists and host firewall. Do not flush firewall rules.
5. Run a bounded manual pipeline in the configured KST window before enabling the timer.
6. Configure healthchecks scheduled deadline, Telegram, Litestream object-storage credentials and
   restore drills. Litestream runs as a separate service, not a replacement for transactional SQLite.

Official Oracle page checked 2026-11-15 states Always Free A1 equivalent is **2 OCPUs / 12 GB**.
It also describes reclamation if, during 7 days, CPU p95 <20%, network <20%, memory <20% (A1).
Do not generate idle traffic/CPU load; owner should verify current tenancy rules / paid-account option.
The page notes an availability-domain exception for South Korea North (Chuncheon); do not assume capacity.
Source: https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm

Playwright ARM64 execution is NOT verified on this Windows x86_64 host. Browser collection is disabled.
The HTTP-only pipeline does not require Chromium. Platform terms, both site parsers and Yeoshin
coupon/base-price parity still require live validation before production.
