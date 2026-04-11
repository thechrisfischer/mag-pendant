# Hardware Research Notes

## Limitless Pendant (LS-PT-01)

The original device this project reverse-engineers. Acquired by Meta (Dec 2025), no longer sold.

### Specs
- **SoC**: Nordic nRF5340 (dual ARM Cortex-M33: 128MHz app + 64MHz net)
- **OS**: Zephyr RTOS 3.5.99, firmware v1.1.20
- **Storage**: SPI NAND flash (~380MB usable via FTL, ~95,232 pages)
- **Audio**: PDM microphones (likely TDK T5838) with beamforming, Opus @ 16kHz mono
- **Wireless**: BLE 5.3 + WiFi (likely nRF7002 companion)
- **Battery**: 230mAh, BQ27427 fuel gauge
- **IMU**: LSM6DSM 6-axis
- **Enclosure**: Sealed (IP54), magnetic clip
- **FCC ID**: [2BL99-LSPT01](https://fcc.report/FCC-ID/2BL99-LSPT01)

### GPIO Pin Map (from limitless-libre)
- PDM: CLK=P1.01, DIN=P1.00, EN=P1.04, THSEL=P1.05, WAKE=P1.02
- I2C: SDA=P1.15, SCL=P1.14
- SPI NAND: SCK=P1.07, MOSI=P1.09, MISO=P1.08
- LED: RGB (P0.22, P0.21, P0.20)
- Button: P0.26 (pull-up, active low)
- Haptic: P0.25

### BLE Protocol
- Audio Service: `632de001-604c-446b-a80f-7963e950f3fb`
- Control (write): `632de002-...`
- Data (notify): `632de003-...`
- Protocol: Google Protocol Buffers, fragmented over BLE
- Encryption: X25519 + ChaCha20-Poly1305 (optional)
- Bonding: Required ("Just Works" pairing)

### Pairing / Factory Reset
- Double-press-and-hold button (tap, release, immediately press+hold)
- Purple light appears → keep holding → release when it disappears
- Solid blue = pairing mode
- Warning: factory reset deletes unsynced recordings

### LED Colors
| Color | Meaning |
|-------|---------|
| Solid blue | Ready to pair |
| White | Recording |
| Orange | Charging |
| Green | Fully charged |
| Purple | Factory reset in progress |
| Red (solid) | Recovery mode |

---

## Sourcing Options

### Secondhand Limitless Pendants
- **eBay**: $150-200 for used units with dock (only source, supply dwindling)
- Original retail: $99 pendant / $299 bundle

### Omi CV1 (Best Alternative) — $89
- Same nRF5340 SoC, dual TDK T5838 PDM mics, BLE 5.2, WiFi 6
- **Fully open source**: PCB schematics, Gerbers, BOM, STEP files (MIT license)
- [omi.me/products/omi](https://www.omi.me/products/omi)
- [github.com/BasedHardware/omi](https://github.com/BasedHardware/omi)

### Magnetic Lavalier Mics (Alternative Approach)
For a simpler workflow (record to onboard flash, sync via USB-C, transcribe locally):

| Device | Storage | Battery | Magnetic | Price |
|--------|---------|---------|----------|-------|
| DJI Mic 2 (TX only) | 8GB | 14hr | Yes | ~$100 |
| Hollyland Lark MAX 2 | 8GB | 14hr | Yes | ~$130 |
| DJI Mic 3 | 32GB | 57hr | Yes | ~$170 |
| Rode Wireless PRO | 32GB | 40hr+ | Yes | ~$250 |

### DIY Components
| Component | Price | Source |
|-----------|-------|--------|
| Omi CV1 open-source PCB | ~$5-10/board | JLCPCB (from Omi Gerbers) |
| nRF5340 module (Fanstel) | ~$8-11 | fanstel.com |
| nRF5340 Audio DK | $169 | DigiKey |
| Seeed XIAO nRF52840 Sense | ~$15 | seeedstudio.com |

---

## Reference Projects
- [sdelcore/pendant-cli](https://github.com/sdelcore/pendant-cli) — Complete BLE protocol RE + Python CLI
- [cipioh/Limitless-Pendant-to-Omi-Sync-macOS](https://github.com/cipioh/Limitless-Pendant-to-Omi-Sync-macOS) — macOS background sync service
- [shade-familiar/limitless-libre](https://github.com/shade-familiar/limitless-libre) — Open-source replacement firmware (early stage)
- [SCTY-Inc/tokdown-mobile](https://github.com/SCTY-Inc/tokdown-mobile) — iOS app for pendant
- [panguin6010/awesome-limitless](https://github.com/panguin6010/awesome-limitless) — Curated project list
