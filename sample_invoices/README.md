# Module 03 demo invoices

PBM-led GPOs ([EVERSANA](https://www.eversana.com/insights/peeking-behind-the-pbm-led-gpo-curtain/)):

- Rosters: ascent=1000 (58 real / 942 dummy), cvs_zinc=1000 (16 real / 984 dummy), optum_emisar=1000 (11 real / 989 dummy), medimpact=220 (14 real / 206 dummy)
- Only **99 real** formulary-linked plans submit on NCPDP (dummies pad the roster)
- **Ascent** — ESI GPO; Prime, Humana, Navitus, Kroger, Blues, Cigna, misc
- **CVS_Zinc** — Zinc GPO; Caremark + CarelonRx (+ SilverScript/Aetna)
- **Optum_Emisar** — Emisar GPO; Optum/UHC only (no non-United externals)
- **MedImpact** — independent PBM, no PBM-led GPO (~220-plan roster)

```bash
python -m netguard.invoice_cli generate sample_invoices/
python -m netguard.invoice_cli run sample_invoices/ --deterministic
```
